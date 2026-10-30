import json, statistics as st

for r, fc in (("qv_S", 4), ("fc_S8", 8), ("fc_S16", 16)):
    ev = [json.loads(l) for l in open(f"traces/{r}/events.jsonl")]
    sv = [e for e in ev if e["event"] == "prefix_saved"]
    cl = [e for e in ev if e["event"] == "prefix_clone"]
    d = [e for e in ev if e["event"] == "rollout_done"]
    b = [e["blocked_s"] for e in sv]
    c = [e["secs"] for e in cl if e["ok"]]
    err = [e for e in d if e.get("error")]
    wall = (max(e["t"] for e in d) - ev[0]["t"]) / 60
    print(f"fork concurrency {fc:>2}: wall {wall:.1f} min, rollouts {len(d)} ({len(err)} with error); saves {len(sv)}, "
          f"clone failures {sum(not e['ok'] for e in cl)}, save failures {sum(e['event'] == 'prefix_save_failed' for e in ev)}; "
          f"rollout blocked per save median {st.median(b):.1f} s (max {max(b):.1f}); clone cmd median {st.median(c):.1f} s (max {max(c):.1f})")
    for e in err:
        print("   error:", e["task"][:8], e["k"], str(e["error"])[-200:])
print("(no cache, same replay: 3.6 min)")
