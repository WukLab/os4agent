"""Epoch metrics of replays vs their live recording: python3 cmp_runs.py LIVE NAME=RUN [NAME=RUN ...]"""
import json, sys


def m(d):
    ev = [json.loads(l) for l in open(f"{d}/events.jsonl")]
    t0 = ev[0]["t"]
    e = sorted((x["t"] - t0) / 60 for x in ev if x["event"] == "rollout_done")
    ws = [(r["t"], r["total"].get("cg_ws_mib", 0) / 1024) for r in map(json.loads, open(f"{d}/mem.jsonl"))]
    gm = sum((ws[i + 1][0] - ws[i][0]) / 60 * ws[i][1] for i in range(len(ws) - 1))
    r = {(x["task"][:8], x["k"]): x["reward"] for x in ev if x["event"] == "rollout_done"}
    return dict(last=e[-1], p99=e[int(len(e) * .99) - 1], t32=e[-1] - e[-33], t16=e[-1] - e[-17],
                peak=max(w for _, w in ws), gm=gm, solved=sum(v > 0 for v in r.values())), r


live, lr = m(sys.argv[1])
runs = [(x.split("=", 1)[0], *m(x.split("=", 1)[1])) for x in sys.argv[2:]]
rows = [("last", "epoch (last rollout done)", "min"), ("p99", "99% of rollouts done", "min"),
        ("t32", "tail from 32 left", "min"), ("t16", "tail from 16 left", "min"),
        ("peak", "peak working set", "GiB"), ("gm", "working set x time", "GiB-min"), ("solved", "solved", "/128")]
print("| | live | " + " | ".join(n for n, _, _ in runs) + " |")
print("|---|---|" + "---|" * len(runs))
for k, lab, unit in rows:
    f = (lambda x: f"{x:.0f}") if k in ("gm", "solved") else (lambda x: f"{x:.2f}")
    cells = [f(v[k]) + ("" if k == "solved" else f" ({(v[k] / live[k] - 1) * 100:+.1f}%)") for _, v, _ in runs]
    print(f"| {lab} ({unit}) | {f(live[k])} | " + " | ".join(cells) + " |")
print("rewards identical to live: " + ", ".join(f"{n} {sum(r.get(k) == lr[k] for k in lr)}/128" for n, _, r in runs))
