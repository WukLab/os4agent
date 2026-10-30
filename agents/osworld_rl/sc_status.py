"""Live status of a --screen-cache replay vs its recording: python3 sc_status.py traces/r128e2_SC traces/rec128e2_shot"""
import glob, json, statistics as st, sys
run, rec = sys.argv[1], sys.argv[2]
ev = [json.loads(l) for l in open(f"{run}/events.jsonl")]
t0 = ev[0]["t"]
T = ev[-1]["t"] - t0
done = [e for e in ev if e["event"] == "rollout_done"]
rv = [json.loads(l) for l in open(f"{rec}/events.jsonl")]
r0 = rv[0]["t"]
rdone = {(e["task"][:8], e["k"]): e for e in rv if e["event"] == "rollout_done"}
chk = [e for e in ev if e["event"] == "scache_check"]
hits = miss = 0
for f in glob.glob(f"{run}/*/*__g*/traj.jsonl"):
    for l in open(f):
        s = json.loads(l)
        if s.get("skipped") == "scache":
            hits += 1
        else:
            miss += 1
print(f"elapsed {T / 60:.1f} min | rollouts done {len(done)} (recording at same time: "
      f"{sum(1 for e in rv if e['event'] == 'rollout_done' and e['t'] - r0 <= T)})")
print(f"steps: served from cache {hits}, run normally {miss} ({hits / max(1, hits + miss):.0%} hits) | checks {len(chk)}: "
      f"ok {sum(e['ok'] for e in chk)}, rejected {sum(not e['ok'] for e in chk)}")
if chk:
    w = [e["waited_s"] for e in chk]
    b = [e["bg_s"] for e in chk]
    print(f"background step s: median {st.median(b):.1f} max {max(b):.1f} | model waited for it: median {st.median(w):.1f} "
          f"p90 {sorted(w)[int(len(w) * .9)]:.1f} max {max(w):.1f}, total {sum(w) / 60:.1f} min")
errs = [(e["task"][:8], e["k"], (e.get("error") or "")[:70]) for e in done if e.get("error")]
print("rollout errors", errs, "| group errors", [e.get("error", "")[:80] for e in ev if e["event"] == "group_error"])
diff = [(e["task"][:8], e["k"], rdone[(e["task"][:8], e["k"])]["reward"], e["reward"], rdone[(e["task"][:8], e["k"])]["steps"], e["steps"])
        for e in done if (e["task"][:8], e["k"]) in rdone and (e["reward"] != rdone[(e["task"][:8], e["k"])]["reward"]
                                                              or e["steps"] != rdone[(e["task"][:8], e["k"])]["steps"])]
print(f"reward/steps vs recording: {len(done) - len(diff)}/{len(done)} identical; differ (task,k,rec r,r,rec steps,steps): {diff}")
if len(done) == 128:
    a = sorted(e["t"] - t0 for e in done); b = sorted(e["t"] - r0 for e in rdone.values())
    print(f"epoch {a[-1] / 60:.2f} vs rec {b[-1] / 60:.2f} min ({a[-1] / b[-1] - 1:+.1%}); 99% {a[126] / 60:.2f} vs {b[126] / 60:.2f}; "
          f"tail 32 left {(a[-1] - a[-33]) / 60:.2f} vs {(b[-1] - b[-33]) / 60:.2f}; solved {sum(e['reward'] > 0 for e in done)} vs "
          f"{sum(e['reward'] > 0 for e in rdone.values())}")
