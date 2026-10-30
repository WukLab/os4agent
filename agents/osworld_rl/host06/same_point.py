import json, sys
for r in sys.argv[1:]:
    ev = [json.loads(l) for l in open(f"traces/{r}/events.jsonl")]
    t0 = ev[0]["t"]
    done = sorted(e["t"] - t0 for e in ev if e["event"] == "rollout_done")
    at = lambda m: sum(t <= m * 60 for t in done)
    print(f"{r:20} rollouts done by 10/15/20 min: {at(10)}/{at(15)}/{at(20)}; 64th done at {done[63] / 60 if len(done) > 63 else float('nan'):.1f} min; last at {done[-1] / 60:.1f} min")
