"""Every task with recorded rollouts in the given runs: rollouts, success rate, median steps -> difficulty spread."""
import glob, json, os, statistics as st, sys, collections
by = collections.defaultdict(list)
for r in sys.argv[1:]:
    for f in glob.glob(f"traces/{r}/*/*__g*/result.txt"):
        d = os.path.dirname(f)
        tj = [json.loads(l) for l in open(f"{d}/traj.jsonl") if l.strip()] if os.path.exists(f"{d}/traj.jsonl") else []
        try:
            rew = float(open(f).read() or 0)
        except ValueError:
            continue
        by[(d.split("/")[2], os.path.basename(d).split("__g")[0][:8])].append((rew, len(tj)))
rate = {k: sum(x[0] > 0 for x in v) / len(v) for k, v in by.items()}
bands = collections.Counter("easy (>=75%)" if p >= .75 else "medium (25-75%)" if p >= .25 else "low (1-25%)" if p > 0 else "never (0%)" for p in rate.values())
print(f"{len(by)} tasks over runs {sys.argv[1:]}: {dict(bands)}")
for app in sorted({k[0] for k in by}):
    ks = [k for k in by if k[0] == app]
    print(f"   {app:20} {len(ks):2} tasks: " + ", ".join(f"{k[1]} {100 * rate[k]:.0f}%/{st.median(x[1] for x in by[k]):.0f}st" for k in sorted(ks, key=lambda k: -rate[k])))
