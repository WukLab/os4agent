"""Failed save clones in the fc runs: when, why, and is the hung rollout (bb5e4c0d k5) the one that was being saved."""
import json

for r in ("fc_S8", "fc_S16"):
    ev = [json.loads(l) for l in open(f"traces/{r}/events.jsonl")]
    t0 = ev[0]["t"]
    print("==", r)
    for e in ev:
        if e["event"] == "prefix_clone" and not e["ok"]:
            w = e["why"]
            w = " ".join(w) if isinstance(w, list) else w
            print(f"  {e['t'] - t0:6.0f}s clone FAILED after {e['secs']:.1f}s: {w[-220:]!r}")
        if e["event"] == "prefix_save_failed":
            print(f"  {e['t'] - t0:6.0f}s save failed g={e['g']} step={e['step']}: {e['error'][-120:]}")
    traj = [json.loads(l) for l in open(f"traces/{r}/chrome/bb5e4c0d-f964-439c-97b6-bdb9747de3f4__g5/traj.jsonl")]
    print("  hung rollout k5 steps:", [(s["step_num"], round(s["exec_s"], 1)) for s in traj][-4:])
