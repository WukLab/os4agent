"""Env time still on the critical path (cache misses) for a run's last rollouts: python3 tail_miss.py traces/<run>"""
import datetime as dt, glob, json, sys
run = sys.argv[1]
ev = [json.loads(l) for l in open(f"{run}/events.jsonl")]
t0 = ev[0]["t"]
done = sorted([e for e in ev if e["event"] == "rollout_done"], key=lambda e: e["t"])
t16 = done[-17]["t"]
for e in done[-6:]:
    d = glob.glob(f"{run}/*/{e['task']}__g{e['k']}")[0]
    tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")]
    ts = [dt.datetime.strptime(t["action_timestamp"], "%Y%m%d@%H%M%S%f").timestamp() for t in tr]
    miss = [t["exec_s"] for t in tr if t.get("skipped") != "scache"]
    tail = [t["exec_s"] for t, s in zip(tr, ts) if t.get("skipped") != "scache" and s >= t16]
    print(f"{e['task'][:8]} k{e['k']}: done {(e['t'] - t0) / 60:.2f} min, {len(tr)} steps, {len(miss)} misses = {sum(miss):.0f} s env; "
          f"after 16 left: {len(tail)} misses = {sum(tail):.0f} s")
