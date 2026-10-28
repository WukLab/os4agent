"""State for the two ways osw_run.py uses the TAGE predictor (toolspec) to skip environment work.

PrefixCache  hashmap hash(system, task, actions so far) -> a checkpoint of the desktop on disk, kept in DIR/index.json so
             every epoch (every osw_run process) sees what earlier ones saved.
ActionBook   remembers each action key's concrete action, so one of TAGE's guessed keys can be turned back into code
             for the desktop as it is now (the target element is found again by role and name).
"""
import copy, hashlib, json, os, threading, time

from a11y_owl_agent import to_code


class PrefixCache:
    def __init__(self, root, depth):
        self.root, self.depth = root, depth
        os.makedirs(root, exist_ok=True)
        self.path = os.path.join(root, "index.json")
        self.index = json.load(open(self.path)) if os.path.exists(self.path) else {}
        self.busy, self.lock = set(), threading.Lock()

    @staticmethod
    def key(system, task, keys):
        return hashlib.sha1(json.dumps([system, task, keys]).encode()).hexdigest()[:20]

    def get(self, system, task, keys):
        """The saved checkpoint for this prefix, or None."""
        with self.lock:
            return self.index.get(self.key(system, task, keys))

    def claim(self, system, task, keys):
        """Reserve a prefix for saving: None if it is too deep, already saved, or being saved by another rollout."""
        k = self.key(system, task, keys)
        with self.lock:
            if len(keys) > self.depth or k in self.index or k in self.busy:
                return None
            self.busy.add(k)
            return k

    def put(self, k, entry):
        with self.lock:
            self.busy.discard(k)
            if entry is not None:
                self.index[k] = {**entry, "saved_at": time.time()}
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
    b = ActionBook()
    b.remember("click push-button|OK", {"action": "click", "id": 5}, {"key": "push-button|OK"})
    rows = [("frame", "W", (0, 0, 10, 10)), ("push-button", "OK", (10, 20, 30, 10))]
    assert b.code_for("click push-button|OK", rows) == "import pyautogui\npyautogui.click(25, 25)"
    assert b.code_for("click push-button|Gone", rows) is None
    print("ok")
