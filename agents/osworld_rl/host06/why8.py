import glob, json, statistics as st
med = lambda v: round(st.median(v), 1) if v else "-"
for r in ("spec_tail_A", "spec_tail_B2", "spec_tail_A8", "spec_tail_B8c"):
    steps = [json.loads(l) for f in glob.glob(f"traces/{r}/*/*/traj.jsonl") for l in open(f) if l.strip()]
    real = [s["exec_s"] for s in steps if s.get("skipped") != "spec"]
    spec = [s["exec_s"] for s in steps if s.get("skipped") == "spec"]
    ev = [json.loads(l) for l in open(f"traces/{r}/events.jsonl")]
    sp = [e for e in ev if e.get("event") == "spec_exec"]
    iv = [(e["t"] - e["total_s"], e["t"] - e["total_s"] + e["fork_s"]) for e in sp if e["fork_s"] > 0]
    conc = [sum(1 for x, y in iv if x < b and y > a) for a, b in iv]
    print(f"{r:14} step after model, run normally: {med(real):5} s | from a hit: {med(spec):5} s | fork {med([e['fork_s'] for e in sp if e['fork_s'] > 0]):5} s"
          f" | forks at once median {med(conc)} max {max(conc) if conc else '-'}")
