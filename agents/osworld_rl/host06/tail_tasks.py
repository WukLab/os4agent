import glob, json, os, statistics as st
med = lambda v: round(st.median(v), 1) if v else "-"
ev = [json.loads(l) for l in open("traces/spec_tail_A8/events.jsonl")]
t0 = ev[0]["t"]
done = sorted((e["t"] - t0, e["task"][:8], e["k"], e["steps"]) for e in ev if e.get("event") == "rollout_done")
print("A8: last 6 rollouts to finish:", [(round(t / 60, 1), task, f"{s} steps") for t, task, k, s in done[-6:]])
print(f"{'task':9} {'A8 step (normal)':>17} {'B8d hit wait':>13} {'B8d miss/normal':>16} {'B8d hits':>9}")
for task in sorted({d[1] for d in done}):
    a = [json.loads(l)["exec_s"] for f in glob.glob(f"traces/spec_tail_A8/*/{task}*/traj.jsonl") for l in open(f) if l.strip()]
    b = [json.loads(l) for f in glob.glob(f"traces/spec_tail_B8d/*/{task}*/traj.jsonl") for l in open(f) if l.strip()]
    hit = [s["exec_s"] for s in b if s.get("skipped") == "spec"]
    norm = [s["exec_s"] for s in b if s.get("skipped") != "spec"]
    print(f"{task:9} {med(a):>17} {med(hit):>13} {med(norm):>16} {len(hit):>4}/{len(b)}")
