"""Trace simulation of a prefix-cache policy for OSWorld GRPO epochs (no desktops run).

  python prefix_sim.py PREV_EPOCH_DIR CUR_EPOCH_DIR [--pool K ...]

Policy (per rollout; the cache key is (task, action keys so far), keys from toolspec.keys.action_key):
  hit   the observation after this action is in the cache (previous epoch, or a sibling of this epoch that already ran it):
        return it at once; the rollout goes "virtual" (its real desktop is behind)
  miss  the real desktop must first reach the prefix, then run the action as usual
  lazy  (policy A) the desktop catches up only at a miss / before scoring: replay the skipped actions, or tfork-clone the
        deepest hot desktop on the path and replay from there
  eager (policy B) the desktop replays skipped actions in the background while the model thinks; a miss waits for it
  hot pool: the K most valuable prefixes of the previous epoch (visits x replay time saved) kept as live desktops
Assumptions: the policy picks the same actions given the same prefix (the recorded epoch is the ground truth), recorded
model-call times (no GPU queueing model), a replayed action costs its recorded exec_s, a clone costs CLONE_S, a cache hit
costs HIT_S. "tail" counts only savings on steps when <= 32 rollouts were live (where spec's gains showed up: earlier the
GPU is saturated and saved env time is absorbed by queueing).
"""
import argparse, glob, hashlib, json, os, re, statistics as st, sys
from collections import defaultdict

sys.path[:0] = [os.path.dirname(os.path.abspath(__file__)), "/mnt/ssd2/vikranth/osworld"]
from toolspec.keys import action_key  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("prev")
ap.add_argument("cur")
ap.add_argument("--pool", type=int, nargs="*", default=[0, 16, 32, 64])
ap.add_argument("--clone-s", type=float, default=2.0, help="tfork clone of a hot desktop (one copy, under load)")
ap.add_argument("--hit-s", type=float, default=0.2, help="serve a cached observation")
ap.add_argument("--key", choices=["prefix", "screen"], default="prefix",
                help="cache key: the action history, or (screen seen, action): different paths reaching the same screen share")
ap.add_argument("--validate", type=int, default=1, help="a hit whose cached next screen differs from the real one is a miss")
ap.add_argument("--tree-depth", type=int, default=0,
                help="policy 2 (in-memory prefix tree): every cached history prefix up to this depth is a live clone")
ap.add_argument("--ws-gib", type=float, default=0.55, help="working set of one idle hot desktop")
a = ap.parse_args()


CLOCK = re.compile(r"\b\d{1,2}:\d{2}( [AP]M)?\b")  # the taskbar clock is the only volatile text seen


def load(root):
    """-> list of rollouts: dict(task, k, start, steps=[dict(key, think, exec, t_avail)], end, reward)"""
    out = []
    for d in glob.glob(f"{root}/*/*__g*"):
        task, k = os.path.basename(d).split("__g")
        ch = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
        tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")]
        if not os.path.exists(f"{d}/timing.json"):  # some old test traces were cut short
            continue
        tm = json.load(open(f"{d}/timing.json"))
        if not tm.get("t_eval") or len(ch) != len(tr):  # errored rollouts (a11y-tree timeout): leave as recorded
            out.append(dict(task=task, k=int(k), start=tm["t_start"], steps=None, end=tm["t_end"]))
            continue
        steps = []
        for i, (c, s) in enumerate(zip(ch, tr)):
            key = action_key(json.loads(s["action"]), s.get("a11y_hit"))
            avail = ch[i + 1]["t"]["obs"] if i + 1 < len(ch) else tm["t_eval"]  # when this step's observation existed
            steps.append(dict(key=key, think=c["t"]["llm_end"] - c["t"]["obs"], exec=s["exec_s"], avail=avail,
                              tree=CLOCK.sub("<clock>", c["messages"][-1]["content"][-1]["text"] if isinstance(c["messages"][-1]["content"], list)
                                    else c["messages"][-1]["content"]).split("Accessibility tree:")[-1]))
        pre = ch[0]["t"]["obs"] - tm["t_start"]
        out.append(dict(task=task, k=int(k), start=tm["t_start"], pre=pre, steps=steps, end=tm["t_eval"],
                        post=tm["t_end"] - tm["t_eval"], reward=float(open(f"{d}/result.txt").read())))
    return out


prev, cur = [r for p in a.prev.split(",") for r in load(p)], load(a.cur)  # prev: one or more earlier trace dirs


def ck(r, i, keys):
    """cache key of step i (keys: the action keys up to and including step i)"""
    if a.key == "screen":
        return r["task"], hashlib.sha1(r["steps"][i]["tree"].encode()).hexdigest(), keys[-1]
    return r["task"], tuple(keys)
t0 = min(r["start"] for r in cur)

# previous-epoch cache: prefix -> (observation tree after it, replay cost of the whole prefix); visit counts for the pool
cache_prev, visits, cost = {}, defaultdict(int), {}
for r in prev:
    if not r["steps"]:
        continue
    keys, c = [], 0.0
    for i, s in enumerate(r["steps"]):
        if s["key"] is None:
            break
        keys.append(s["key"])
        c += s["exec"]
        p = ck(r, i, keys)
        visits[p] += 1
        cost.setdefault(p, c)
        nxt = r["steps"][i + 1]["tree"] if i + 1 < len(r["steps"]) else None
        cache_prev.setdefault(p, nxt)

done_prev = {(r["task"], tuple(s["key"] for s in r["steps"][:-1])): r["reward"] for r in prev
             if r["steps"] and r["steps"][-1]["key"] is None}

# this epoch's own entries become usable once a sibling has really run them (recorded time: conservative)
cache_cur = {}
for r in cur:
    if not r["steps"]:
        continue
    keys = []
    for i, s in enumerate(r["steps"]):
        if s["key"] is None:
            break
        keys.append(s["key"])
        p = ck(r, i, keys)
        nxt = r["steps"][i + 1]["tree"] if i + 1 < len(r["steps"]) else None
        cache_cur.setdefault(p, []).append((s["avail"], nxt))

live_at = sorted(r["end"] for r in cur)
def live(t):  # rollouts still running at recorded time t
    return sum(1 for e in live_at if e > t)


def in_tree(r, keys, at):
    """policy 2: this history prefix is a live clone by recorded time `at` (rollout-relative): saved last epoch, or by a
    rollout of this epoch that really ran it (needs history keys)"""
    p = (r["task"], tuple(keys))
    return p in cache_prev or any(t <= r["start"] + at for t, _ in cache_cur.get(p, []))


def pool_of(k):
    """the k prefixes of the previous epoch worth keeping hot: (visits - 1) x replay time, deeper than 1 step"""
    cand = [((v - 1) * cost[p], p) for p, v in visits.items() if v >= 2 and len(p[1]) >= 2]
    return {p for _, p in sorted(cand, reverse=True)[:k]}


def sim(r, pool, eager):
    """-> (new duration, saved s on tail steps, stats)"""
    if not r["steps"]:
        return r["end"] - r["start"], 0.0, dict(hits=0, steps=0, clones=0, replayed=0, same_tree=0, cmp=0)
    now = r["pre"]
    real, virt = 0, 0  # prefix lengths: the real desktop / where the agent is
    worker = now  # eager: when the background replay finishes
    keys, st_ = [], dict(hits=0, steps=0, clones=0, replayed=0, same_tree=0, cmp=0, reward_cached=0, rejected=0)
    tail_saved, base_t = 0.0, r["pre"]
    ex = [s["exec"] for s in r["steps"]]

    def catch_up(target, at):
        """time for the real desktop to go from `real` to `target` starting at `at` (clone a hot desktop if it helps)"""
        nonlocal real
        best = (sum(ex[real:target]), None)
        for d in range(target, real, -1):
            if (r["task"], tuple(keys[:d])) in pool or (a.tree_depth and d <= a.tree_depth and in_tree(r, keys[:d], at)):
                c = a.clone_s + sum(ex[d:target])
                if c < best[0]:
                    best = (c, d)
                break  # deepest hot ancestor only
        if best[1] is not None:
            st_["clones"] += 1
        st_["replayed"] += target - (best[1] or real)
        real = target
        return at + best[0]

    for i, s in enumerate(r["steps"]):
        st_["steps"] += 1
        now += s["think"]
        base_t += s["think"]
        base_step = s["exec"]
        if s["key"] is None:  # done: the desktop must be at the prefix before scoring, unless the whole path is cached
            if (r["task"], tuple(keys)) in done_prev:
                st_["reward_cached"] += 1
                now += a.hit_s
            else:
                end = max(now, worker) if eager else catch_up(virt, now)
                now = end + s["exec"]
            base_t += base_step
            break
        keys.append(s["key"])
        p = ck(r, i, keys)
        t_abs = r["start"] + now
        if p in cache_prev:
            ref = cache_prev[p]
        else:
            ref = min((x for x in cache_cur.get(p, []) if x[0] <= t_abs), default=(None, None))
            ref = ref[1] if ref[0] is not None else False  # False: not in the cache yet
        actual = r["steps"][i + 1]["tree"] if i + 1 < len(r["steps"]) else None
        hit = ref is not False
        if hit and a.validate and ref is not None and actual is not None and ref != actual:
            hit = False  # the desktop's real screen disagrees: the served observation is withdrawn, a miss
            st_["rejected"] += 1
        if hit:
            st_["hits"] += 1
            if ref is not None and actual is not None:
                st_["cmp"] += 1
                st_["same_tree"] += ref == actual
            virt += 1
            if eager:
                if p in pool and real < virt:  # jump the background desktop onto the hot copy
                    worker, real = max(worker, now) + a.clone_s, virt
                    st_["clones"] += 1
                else:
                    worker = max(worker, now) + s["exec"]
                    real = virt
                    st_["replayed"] += 1
            now += a.hit_s
            saved = base_step - a.hit_s
        else:
            if eager:
                start = max(now, worker)
            else:
                start = catch_up(virt, now)
            waited = start - now
            now = start + s["exec"]
            virt = real = virt + 1
            worker = now
            saved = -waited
        if live(r["start"] + base_t) <= 32:
            tail_saved += saved
        base_t += base_step
    return now + (0.0 if st_["reward_cached"] else r["post"]), tail_saved, st_


base_end = max(r["end"] for r in cur) - t0
base_tail = sorted(r["end"] - t0 for r in cur)
print(f"key {a.key} | prev {a.prev}: {len(prev)} rollouts, {len(cache_prev)} prefixes | cur {a.cur}: {len(cur)} rollouts")
print(f"baseline: epoch {base_end / 60:.2f} min, env time {sum(sum(s['exec'] for s in r['steps']) for r in cur if r['steps']) / 60:.0f} "
      f"rollout-min of {sum((r['end'] - r['start']) for r in cur) / 60:.0f}")
for eager in (False, True):
    for k in a.pool:
        pool = pool_of(k)
        res = [(r, *sim(r, pool, eager)) for r in cur]
        ends = sorted(r["start"] - t0 + d for r, d, _, _ in res)
        tot = defaultdict(int)
        for _, _, _, s in res:
            for x, v in s.items():
                tot[x] += v
        tail = sum(ts for _, _, ts, _ in res)
        last = ends[-1]
        # tail-only estimate: the epoch end moves by what the last-finishing rollout saved on its tail steps
        lr = max(res, key=lambda x: x[0]["end"])
        print(f"{'eager' if eager else 'lazy '} pool {k:3d} ({k * a.ws_gib:4.1f} GiB): hit {tot['hits'] / tot['steps']:.0%} of steps, "
              f"obs identical {tot['same_tree'] / max(1, tot['cmp']):.0%}, rejected {tot['rejected']}, reward cached {tot['reward_cached']}, clones {tot['clones']}, replayed {tot['replayed']} | "
              f"epoch {last / 60:.2f} min ({last / base_end - 1:+.1%}), 99% {ends[int(len(ends) * .99) - 1] / 60:.2f} "
              f"(base {base_tail[int(len(ends) * .99) - 1] / 60:.2f}) | tail-only: last rollout saves {lr[2]:.0f} s "
              f"-> {(base_end - lr[2]) / 60:.2f} min ({-lr[2] / base_end:+.1%})")
