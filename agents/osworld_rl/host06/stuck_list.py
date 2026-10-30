"""Tasks with a rollout stuck at the cap (one action >= 4 of the last 8 steps) in a run -> stuck.json"""
import json, glob, sys
from collections import Counter
run = sys.argv[1]
stuck = {}
for e in map(json.loads, open(f"traces/{run}/events.jsonl")):
    if e["event"] != "rollout_done" or e["steps"] < 15 or e["reward"] >= 0.9: continue
    f = glob.glob(f"traces/{run}/*/{e['task']}__g{e['k']}/traj.jsonl")[0]
    rows = [json.loads(l) for l in open(f) if l.strip()]
    keys = [(r.get("action") or "") + "|" + ((r.get("a11y_hit") or {}).get("key") or "") for r in rows]
    if Counter(keys[7:]).most_common(1)[0][1] >= 4:
        stuck.setdefault(f.split("/")[2], set()).add(e["task"])
out = {a: sorted(v) for a, v in stuck.items()}
json.dump(out, open("stuck.json", "w"), indent=1)
print({a: [t[:8] for t in v] for a, v in out.items()}, sum(map(len, out.values())), "tasks")
