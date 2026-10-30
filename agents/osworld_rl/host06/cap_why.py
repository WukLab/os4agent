"""Why rollouts hit the step cap: stuck repeating one action / still exploring / solved but kept going. Usage: cap_why.py <run> [cap]"""
import json, glob, sys
from collections import Counter
run, cap = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 15
cat, ex, n = Counter(), {}, 0
for e in map(json.loads, open(f"traces/{run}/events.jsonl")):
    if e["event"] != "rollout_done": continue
    n += 1
    if e["steps"] < cap: continue
    f = glob.glob(f"traces/{run}/*/{e['task']}__g{e['k']}/traj.jsonl")[0]
    rows = [json.loads(l) for l in open(f) if l.strip()]
    keys = [(r.get("action") or "") + "|" + ((r.get("a11y_hit") or {}).get("key") or "") for r in rows]
    top = Counter(keys[7:]).most_common(1)[0][1]
    c = ("solved, kept going" if e["reward"] >= 0.9 else "stuck repeating one action" if top >= 4
         else "cycling among a few actions" if len(set(keys)) <= 6 else "still exploring")
    cat[c] += 1; ex.setdefault(c, set()).add(f.split("/")[2][:18] + " " + e["task"][:8])
tot = sum(cat.values())
print(f"{run}: {tot}/{n} rollouts hit the cap ({100 * tot / max(n, 1):.0f}%)")
for c, k in cat.most_common(): print(f"  {k:2d} ({100 * k / tot:3.0f}%) {c}: {sorted(ex[c])[:6]}")
