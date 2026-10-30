"""Per task in a run: successes, median steps, median rollout time (step-only), share at the step cap."""
import glob, json, os, statistics as st, sys
r = sys.argv[1]
by = {}
for f in glob.glob(f"traces/{r}/*/*/timing.json"):
    d = os.path.dirname(f)
    tm = json.load(open(f))
    task = os.path.basename(d).split("__g")[0][:8]
    rew = float(open(f"{d}/result.txt").read() or 0)
    by.setdefault((d.split("/")[2], task), []).append((rew, tm.get("steps", 0), (tm.get("t_eval") or tm["t_end"]) - tm["t_start"]))
print(f"{'app':17} {'task':9} {'ok/8':>5} {'median steps':>13} {'at cap':>7} {'median min':>11}")
for (app, task), v in sorted(by.items(), key=lambda kv: st.median(x[2] for x in kv[1])):
    print(f"{app:17} {task:9} {sum(x[0] > 0 for x in v):>3}/8 {st.median(x[1] for x in v):>13.0f} {sum(x[1] >= 15 for x in v):>5}/8 {st.median(x[2] for x in v) / 60:>11.1f}")
