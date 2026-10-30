"""For one rollout of a prefix+spec run: at each step, which pre-fork condition held. python3 spec_gates.py RUN TASK K"""
import glob, json, statistics, sys
run, task, k = sys.argv[1], sys.argv[2], int(sys.argv[3])
d = glob.glob(f"{run}/*/{task}*__g{k}")[0]
tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")]
ev = [json.loads(l) for l in open(f"{run}/events.jsonl")]
env_all = [s["exec_s"] for f in glob.glob(f"{run}/*/*__g*/traj.jsonl") for s in map(json.loads, open(f))]
med = statistics.median(env_all)
print(f"{d.split('/')[-1]}: {len(tr)} steps; run's median env step {med:.2f} s (spec-slow compares with this)")
for i, s in enumerate(tr):
    prev = tr[i - 1] if i else None
    idle = prev is None or prev.get("skipped") != "scache"
    slow = prev is not None and prev["exec_s"] >= med
    print(f"step {i + 1:2d}: {'cache hit' if s.get('skipped') == 'scache' else 'spec' if s.get('skipped') == 'spec' else 'normal   '}"
          f" exec {s['exec_s']:6.2f} | desktop idle before it: {'yes' if idle else 'no '} | previous step slow: {'yes' if slow else 'no '}")
print("speculation events for this task:", [(e.get("outcome")) for e in ev if e["event"] == "spec_exec" and e["task"].startswith(task)])
