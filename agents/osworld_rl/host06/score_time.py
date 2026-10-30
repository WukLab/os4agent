import glob, json, statistics as st, sys
for r in sys.argv[1:]:
    s = []
    for f in glob.glob(f"traces/{r}/*/*/timing.json"):
        t = json.load(open(f))
        if t.get("t_eval") and t.get("t_end"):
            s.append((t["t_end"] - t["t_eval"], f.split("/")[2], f.split("/")[3][:8]))
    v = sorted(x[0] for x in s)
    print(f"{r:20} scoring time over {len(v)} rollouts: median {st.median(v):.1f} s, p90 {v[int(.9 * (len(v) - 1))]:.1f} s, max {v[-1]:.0f} s, total {sum(v) / 60:.0f} rollout-min; slowest: {sorted(s)[-3:]}")
