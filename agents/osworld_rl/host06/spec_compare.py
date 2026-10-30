import json, statistics as st
for r in ("A8", "B8c", "B8d", "B8e"):
    root = f"traces/spec_tail_{r}"
    ev = [json.loads(l) for l in open(f"{root}/events.jsonl")]
    t0 = ev[0]["t"]
    done = [e for e in ev if e["event"] == "rollout_done"]
    fk = min(e["t"] for e in ev if e["event"] == "fork")
    ws = [json.loads(l)["total"].get("cg_ws_mib", 0) / 1024 for l in open(f"{root}/mem.jsonl")]
    ends = sorted(e["t"] - t0 for e in done)
    rew = {}
    for e in done:
        rew.setdefault(e["task"][:8], []).append(e["reward"])
    print(f"{r:3}: wall {(max(e['t'] for e in done) - t0) / 60:.1f} min (first fork at {(fk - t0) / 60:.1f}), rollouts {len(done)}, "
          f"errors {sum(bool(e['error']) for e in done)}, steps {sum(e['steps'] for e in done)}, rollout median {st.median(e['secs'] for e in done) / 60:.1f} min, "
          f"half done at {ends[len(ends) // 2] / 60:.1f} min; working set peak {max(ws):.1f} GiB, mean {st.mean(ws):.1f}")
    print("     reward sum per task", {k: sum(v) for k, v in sorted(rew.items())})
