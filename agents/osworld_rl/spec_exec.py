"""State for the two ways osw_run.py uses the TAGE predictor (toolspec) to skip environment work.

PrefixCache  hashmap hash(system, task, actions so far) -> a checkpoint of the desktop on disk, kept in DIR/index.json so
             every epoch (every osw_run process) sees what earlier ones saved. Each entry records when (and in which
             epoch) it was saved and last restored; evict() drops the ones untouched since a given time.
ActionBook   remembers each action key's concrete action, so one of TAGE's guessed keys can be turned back into code
             for the desktop as it is now (the target element is found again by role and name).
"""
import collections, copy, hashlib, json, os, threading, time

from a11y_owl_agent import to_code


EXACT_FIELDS = ("action", "id", "from", "to", "text", "keys", "direction")  # what to_code() turns into the action


def exact_key(act):
    """The prefix cache's key for an action: the action itself, element ids included. Unlike action_key (role|name of
    the target, no drag destination), two different actions never share it; ids are comparable because a cache hit
    means the desktop was the same before every earlier action of the prefix."""
    return json.dumps({k: act[k] for k in EXACT_FIELDS if k in act}, sort_keys=True)


class PrefixCache:
    def __init__(self, root, depth):
        self.root, self.depth = root, depth
        os.makedirs(root, exist_ok=True)
        self.path = os.path.join(root, "index.json")
        self.index = json.load(open(self.path)) if os.path.exists(self.path) else {}
        self.busy, self.pinned, self.lock = set(), collections.Counter(), threading.Lock()
        # rollouts that reached each prefix (key -> count, whether or not it is cached), kept across runs: admission
        self.visits_path = os.path.join(root, "visits.json")
        self.visits = collections.Counter(json.load(open(self.visits_path)) if os.path.exists(self.visits_path) else {})
        # known continuations of each prefix (parent key -> child keys): saved entries, and actions decided in this run
        self.kids = collections.defaultdict(set)
        for k, e in self.index.items():
            if e and e.get("parent"):
                self.kids[e["parent"]].add(k)
        # gdsf (greedy-dual): an entry's priority h = clock + its step's desktop time x (1 + hits), set when it is saved
        # or hit; eviction takes the lowest h and moves the clock up to it, so entries nobody hits age out
        self.clock = min((e["h"] for e in self.index.values() if e and "h" in e), default=0.0)
        # this run's schedule (task -> position in the run order) and progress: each task's tree is used once per
        # epoch, when its group runs, so victims() takes first from tasks whose group is done (next use: next epoch),
        # then from pending tasks, the latest scheduled first, and from running groups last
        self.schedule, self.running, self.finished = {}, set(), set()

    @staticmethod
    def key(system, task, keys):
        return hashlib.sha1(json.dumps([system, task, keys]).encode()).hexdigest()[:20]

    def get(self, system, task, keys):
        """The saved checkpoint for this prefix, or None."""
        with self.lock:
            return self.index.get(self.key(system, task, keys))

    def claim(self, system, task, keys, upgrade=False):
        """Reserve a prefix for saving: None if it is too deep, already saved, or being saved by another rollout.
        upgrade: an entry without a snapshot (a reply) may get one."""
        k = self.key(system, task, keys)
        with self.lock:
            saved = k in self.index and (not upgrade or "mem" in (self.index[k] or {}))
            if len(keys) > self.depth or saved or k in self.busy:
                return None
            self.busy.add(k)
            return k

    def refuse(self, system, task, keys, tree, admit, step_s=0.0, admit_cost=0.0):
        """Why a prefix may not be saved, or None: tree -- its parent prefix is neither cached nor being saved (the
        cache stays a tree: every entry's ancestors are cached; a child of a parent still being saved registers after
        it, wait_saved()); admit -- its parent was reached by fewer than `admit` rollouts; admit_cost -- the hits it can
        expect (the other rollouts that reached its parent) x `step_s`, the desktop time of the path to it from the
        root (not its own step alone: a cheap step whose children are expensive would block them in tree mode), are
        under `admit_cost` seconds (what a save costs)."""
        if not keys:
            return None
        p = self.key(system, task, keys[:-1])
        with self.lock:
            if tree and p not in self.index and p not in self.busy:
                return "no_parent"
            if admit and self.visits[p] < admit:
                return "admission"
            if admit_cost and (self.visits[p] - 1) * step_s < admit_cost:
                return "admission_cost"
        return None

    def wait_saved(self, k, timeout):
        """Wait while k is being saved. -> whether it is cached"""
        t0 = time.time()
        while True:
            with self.lock:
                if k in self.index:
                    return True
                if k not in self.busy:
                    return False
            if time.time() - t0 > timeout:
                return False
            time.sleep(0.2)

    def note_end(self, system, task, keys):
        """A rollout ended at `keys`. -> how many rollouts have ended there (0: no entry for it)"""
        k = self.key(system, task, keys)
        with self.lock:
            e = self.index.get(k)
            if not e:
                return 0
            e["ends"] = e.get("ends", 0) + 1
            self._write()
            return e["ends"]

    def visit(self, system, task, keys):
        with self.lock:
            self.visits[self.key(system, task, keys)] += 1

    def save_visits(self):
        with self.lock:
            tmp = self.visits_path + ".tmp"
            json.dump(self.visits, open(tmp, "w"))
            os.replace(tmp, self.visits_path)

    def with_descendants(self, keys):
        """keys plus every cached entry below them (tree mode: dropping a node drops its subtree)."""
        with self.lock:
            kids = collections.defaultdict(list)
            for k, e in self.index.items():
                if e and e.get("parent"):
                    kids[e["parent"]].append(k)
        out, todo = set(), list(keys)
        while todo:
            k = todo.pop()
            if k not in out:
                out.add(k)
                todo += kids[k]
        return out

    def put_new(self, k, entry):
        """put() unless k is in the index already. -> whether it was added"""
        with self.lock:
            if k in self.index:
                return False
            self.index[k] = {**entry, "saved_at": time.time()}
            self._write()
            return True

    def attach(self, k, fields):
        """Add fields (a snapshot) to an existing entry (a reply). -> whether the entry exists"""
        with self.lock:
            if k not in self.index:
                return False
            self.index[k].update(fields, saved_at=time.time())
            self._write()
            return True

    def detach(self, keys, fields=("mem", "pid")):
        """Drop the snapshot of these entries, keep the rest (their replies)."""
        with self.lock:
            for k in keys:
                for f in fields:
                    (self.index.get(k) or {}).pop(f, None)
            self._write()

    def put(self, k, entry):
        with self.lock:
            self.busy.discard(k)
            if entry is not None:
                self.index[k] = {**entry, "saved_at": time.time()}
                self._prioritize(self.index[k])
                self._write()

    def _prioritize(self, e):  # under self.lock
        e["h"] = round(self.clock + e.get("step_s", e.get("benefit_s", 0.0)) * (1 + e.get("hits", 0)), 3)

    def release(self, k):
        """Give up a claim without saving."""
        with self.lock:
            self.busy.discard(k)

    def touch(self, system, task, keys, epoch):
        """Record a successful restore of this prefix (eviction keeps what recent epochs used)."""
        k = self.key(system, task, keys)
        with self.lock:
            if k in self.index:
                e = self.index[k]
                e.update(used_at=time.time(), used_epoch=epoch, hits=e.get("hits", 0) + 1)
                self._prioritize(e)
                self._write()

    def pin(self, k):
        """While an entry is being restored from, victims() won't pick it."""
        with self.lock:
            self.pinned[k] += 1

    def unpin(self, k):
        with self.lock:
            self.pinned[k] -= 1
            if self.pinned[k] <= 0:
                del self.pinned[k]

    def victims(self, sizes, need, budget, policy, tree=False, roots_last=False, done_only=False):
        """Entries to drop so that sum(sizes) + need <= budget, in eviction order: lru = least recently saved or
        restored first; lfu = fewest hits first (ties: least recent); gdsf = lowest priority h first (the desktop time
        its step took x (1 + hits), plus the clock when it was saved or last hit). Before the policy: entries of tasks
        whose group is done go first, then pending tasks' (latest scheduled first), running groups' last (schedule).
        done_only: only non-root entries of tasks whose group is done (or not in the schedule) may go -- for a new save,
        whose next use is the next epoch: evicting what a pending group needs this epoch, or a root, for it is a loss. tree: only leaves (entries no cached entry has as
        parent) go, so a parent becomes a candidate once its children are gone. roots_last: depth-0 entries go only
        when nothing else is left. sizes: key -> MiB of every entry.
        -> [keys], or None when even dropping every unpinned (leaf) entry is not enough."""
        with self.lock:
            last = lambda k: max(self.index[k].get("saved_at", 0), self.index[k].get("used_at", 0))
            order = {"lru": lambda k: last(k), "lfu": lambda k: (self.index[k].get("hits", 0), last(k)),
                     "gdsf": lambda k: (self.index[k].get("h", self.clock), last(k))}[policy]
            n = len(self.schedule)

            def due(k):  # 0 = needed last (its group is done this run) ... n + 1 = needed now (its group is running)
                t = self.index[k].get("task")
                if t not in self.schedule or t in self.finished:
                    return 0
                return n + 1 if t in self.running else n - self.schedule[t]
            key = lambda k: (roots_last and self.index[k].get("depth") == 0, due(k), order(k))
            # done_only (a new save): never a root either -- losing one costs its task boot + setup and all its hits
            # next epoch; only memory growth may take a root
            cand = sorted((k for k in self.index if k not in self.pinned and k in sizes
                           and (not done_only or (due(k) == 0 and self.index[k].get("depth") != 0))), key=key)
            parent = {k: (self.index[k] or {}).get("parent") for k in self.index}
        kids = collections.Counter(p for p in parent.values() if p) if tree else collections.Counter()
        total, out = sum(sizes.values()), []
        while total + need > budget:
            k = next((k for k in cand if not kids[k]), None)  # in order: the first one that is a leaf
            if k is None:
                break
            cand.remove(k)
            total -= sizes[k]
            out.append(k)
            if parent.get(k):
                kids[parent[k]] -= 1
        if out and policy == "gdsf":
            with self.lock:
                self.clock = max([self.clock] + [(self.index.get(k) or {}).get("h", 0.0) for k in out])
        return out if total + need <= budget else None

    def drop(self, keys):
        with self.lock:
            for k in keys:
                self.index.pop(k, None)
            self._write()

    def evict(self, before, remove):
        """Drop every entry neither saved nor restored since `before` (a timestamp); remove(entry) frees its
        snapshot. -> number of entries dropped"""
        with self.lock:
            old = {k: e for k, e in self.index.items() if max(e.get("saved_at", 0), e.get("used_at", 0)) < before}
        for e in old.values():
            remove(e)
        with self.lock:
            for k in old:
                self.index.pop(k, None)
            self._write()
        return len(old)

    def _write(self):  # under self.lock
        tmp = self.path + ".tmp"
        json.dump(self.index, open(tmp, "w"), indent=1)
        os.replace(tmp, self.path)


class ActionBook:
    def __init__(self):
        self.acts, self.lock = {}, threading.Lock()

    def remember(self, key, act, hit):
        if key is not None:
            with self.lock:
                self.acts.setdefault(key, (copy.deepcopy(act), hit))

    def code_for(self, key, rows):
        """Code that performs the action `key` on the desktop whose elements are `rows`, or None if it can't."""
        with self.lock:
            if key not in self.acts:
                return None
            act, hit = copy.deepcopy(self.acts[key])
        if act.get("action") == "drag":
            return None  # two targets; the key only names one
        if hit:  # re-find the target element by role and name
            idx = next((j for j, r in enumerate(rows) if f"{r[0]}|{r[1][:60]}" == hit["key"]), None)
            if idx is None:
                return None
            act["id"] = idx
        try:
            return to_code(act, rows)
        except Exception:
            return None


if __name__ == "__main__":  # self-check: python spec_exec.py
    import tempfile
    d = tempfile.mkdtemp()
    c = PrefixCache(d, depth=2)
    k = c.claim("tfork", "t1", ["click a"])
    assert k and c.claim("tfork", "t1", ["click a"]) is None  # reserved
    c.put(k, {"path": "x"})
    assert PrefixCache(d, 2).get("tfork", "t1", ["click a"])["path"] == "x"  # survives a new process
    assert c.claim("tfork", "t1", ["a", "b", "c"]) is None  # deeper than depth
    t_mid = time.time()
    k2 = c.claim("tfork", "t1", ["click b"])
    c.put(k2, {"path": "y"})
    c.touch("tfork", "t1", ["click a"], epoch=1)  # restored after t_mid: kept
    k3 = c.claim("tfork", "t2", ["click c"])
    c.put(k3, {"path": "z"})
    c.index[k3]["saved_at"] = t_mid - 1  # saved before t_mid, never restored: evicted
    sizes = {k: 100 for k in c.index}  # click a (hits 1), click b, click c (oldest)
    assert c.victims(sizes, need=100, budget=250, policy="lru") == [k3, k2]
    assert c.victims(sizes, need=100, budget=250, policy="lfu") == [k3, k2]  # 0 hits each, then least recent
    c.pin(k3)
    assert c.victims(sizes, need=100, budget=250, policy="lru") == [k2, k]
    assert c.victims(sizes, need=100, budget=150, policy="lru") is None  # k3 is pinned: can't get under
    c.unpin(k3)
    gone = []
    assert c.evict(t_mid, gone.append) == 1 and gone[0]["path"] == "z"
    assert PrefixCache(d, 2).get("tfork", "t1", ["click a"])["used_epoch"] == 1 and c.get("tfork", "t2", ["click c"]) is None
    assert exact_key({"action": "drag", "from": 3, "to": 7}) != exact_key({"action": "drag", "from": 3, "to": 9})
    assert exact_key({"action": "click", "id": 5, "reason": "x"}) == exact_key({"id": 5, "action": "click"})
    b = ActionBook()
    b.remember("click push-button|OK", {"action": "click", "id": 5}, {"key": "push-button|OK"})
    rows = [("frame", "W", (0, 0, 10, 10)), ("push-button", "OK", (10, 20, 30, 10))]
    assert b.code_for("click push-button|OK", rows) == "import pyautogui\npyautogui.click(25, 25)"
    assert b.code_for("click push-button|Gone", rows) is None
    print("ok")
