"""Replaying the same recording twice through the cache (run_tree8_same.sh): what the second pass could have hit and
why it didn't. A step <= depth of the second pass is
  hit          answered from the cache
  never saved  the first pass didn't save that prefix (admission, no parent, no room, or a prefix it never reached)
  evicted      the first pass saved it, eviction removed it before the second pass got there
  other        saved and not evicted, yet missed (e.g. an earlier step of the rollout already missed: a miss forks a
               desktop and the rollout runs on it, but later hits are still possible; or a different action)

  python3 -I same_check.py <first pass dir> <second pass dir> [--depth 8]
"""
import argparse, collections, glob, json, os, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spec_exec import PrefixCache, exact_key  # noqa: E402
from toolspec.keys import action_key  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("first")
ap.add_argument("second")
ap.add_argument("--depth", type=int, default=8)
a = ap.parse_args()


def jl(p):
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []


key = lambda task, keys: PrefixCache.key("tfork", task, keys)
saved, evicted_at = set(), {}
for run in (a.first, a.second):
    for e in jl(Path(run) / "events.jsonl"):
        if e["event"] == "prefix_saved" and e.get("key"):
            saved.add(e["key"])
        elif e["event"] == "prefix_evict" and e.get("key"):
            evicted_at.setdefault(e["key"], (run, e["t"], e.get("task_state")))
saved_first = {e["key"] for e in jl(Path(a.first) / "events.jsonl") if e["event"] == "prefix_saved" and e.get("key")}
c, by = collections.Counter(), collections.defaultdict(collections.Counter)
for f in glob.glob(f"{a.second}/*/*__g*/traj.jsonl"):
    task = Path(f).parent.name.split("__g")[0]
    hist = []
    for s in jl(f):
        act = json.loads(s["action"])
        if action_key(act, s.get("a11y_hit")) is None:
            continue
        hist.append(exact_key(act))
        n = s["step_num"]
        if n > a.depth:
            continue
        k = key(task, hist)
        why = ("hit" if s.get("lazy") else "never saved" if k not in saved_first else
               "evicted" if k in evicted_at else "other")
        c[why] += 1
        by[n][why] += 1
tot = sum(c.values())
print(f"second pass, steps <= {a.depth}: {tot}: " + ", ".join(f"{w} {c[w]} ({100 * c[w] / tot:.0f}%)" for w in ("hit", "never saved", "evicted", "other")))
for n in sorted(by):
    t = sum(by[n].values())
    print(f"  step {n}: " + " ".join(f"{w} {100 * by[n][w] / t:3.0f}%" for w in ("hit", "never saved", "evicted", "other")))
ev_states = collections.Counter(st for run, _, st in evicted_at.values() if run == a.second)
print(f"evictions during the second pass by task state: {dict(ev_states)}")
