"""Per-step harness overhead of a replay vs its recording: the gap between two actions minus the step's exec_s and
the next recorded model call. python3 sc_overhead.py traces/<run> traces/<recording>"""
import datetime as dt, glob, json, statistics as st, sys
run, rec = sys.argv[1], sys.argv[2]
o = {"after a cache hit": [], "after a normal step": []}
for d in glob.glob(f"{run}/*/*__g*"):
    try:
        tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")]
        ch = [json.loads(l) for l in open(d.replace(run, rec) + "/chat.jsonl")]
    except OSError:
        continue
    ts = [dt.datetime.strptime(t["action_timestamp"], "%Y%m%d@%H%M%S%f").timestamp() for t in tr]
    for i in range(min(len(tr), len(ch)) - 1):
        t = ch[i + 1].get("t") or {}
        g = ts[i + 1] - ts[i] - tr[i]["exec_s"] - (t.get("llm_end", 0) - t.get("llm_start", 0))
        o["after a cache hit" if tr[i].get("skipped") in ("scache", "prefix") else "after a normal step"].append(g)
for k, v in o.items():
    if v:
        print(f"{k}: {len(v)} steps, overhead median {st.median(v):.2f} s, p90 {sorted(v)[int(len(v) * .9)]:.2f} s")
