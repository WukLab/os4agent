"""Step-only epoch timing: each rollout ends at t_eval (its last step done, before OSWorld scoring), so a hung scorer
doesn't count. Per run: epoch time, 64th / last rollout, tail, speculation stats. python step_only.py RUN..."""
import glob, json, statistics as st, sys
for r in sys.argv[1:]:
    ev = [json.loads(l) for l in open(f"traces/{r}/events.jsonl")]
    t0 = ev[0]["t"]
    ends = sorted(json.load(open(f))["t_eval"] - t0 for f in glob.glob(f"traces/{r}/*/*/timing.json") if json.load(open(f)).get("t_eval"))
    full = sorted(e["t"] - t0 for e in ev if e["event"] == "rollout_done")
    sp = [e for e in ev if e["event"] == "spec_exec"]
    med = lambda v: f"{st.median(v):.1f}" if v else "-"
    t64 = ends[63] if len(ends) > 63 else float("nan")
    print(f"{r}: steps-only: 64th {t64 / 60:.1f} min, last {ends[-1] / 60:.1f} min, tail {(ends[-1] - t64) / 60:.1f} min "
          f"({len(ends)} rollouts) | with scoring: last {full[-1] / 60:.1f} min")
    if sp:
        print(f"   spec: {len(sp)} steps, {sum(e['hit'] is not None for e in sp)} hits, fork {med([e['fork_s'] for e in sp if e['fork_s'] > 0])} s, "
              f"wait on hit {med([e['waited_s'] for e in sp if e['hit'] is not None])} s, errors {sum(bool(e['error']) for e in sp)}")
