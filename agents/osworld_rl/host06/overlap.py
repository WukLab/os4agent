"""Do speculation's wins (P2) fall on steps the screen cache already serves (SC2)? python3 overlap.py P2 SC2"""
import glob, json, os, sys
p2, sc = sys.argv[1], sys.argv[2]
won = hit = 0
won_late = hit_late = 0
saved = saved_cached = 0.0
for f in glob.glob(f"{p2}/*/*__g*/traj.jsonl"):
    rel = os.path.relpath(f, p2)
    a = [json.loads(l) for l in open(f)]
    b = [json.loads(l) for l in open(f"{sc}/{rel}")]
    for i, s in enumerate(a):
        if s.get("skipped") != "spec":
            continue
        won += 1
        cached = i < len(b) and b[i].get("skipped") == "scache"
        hit += cached
        if i >= 10:
            won_late += 1
            hit_late += cached
print(f"steps speculation took over in P2: {won}; the same step was a cache hit in the prefix-cache run: {hit} ({hit / won:.0%})")
print(f"  of those at step 11 or later: {won_late}; cache hit there too: {hit_late} ({hit_late / max(1, won_late):.0%})")
