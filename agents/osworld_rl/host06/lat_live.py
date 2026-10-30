import glob, json, statistics as st, sys
for r in sys.argv[1:]:
    ev = [json.loads(l) for l in open(f"traces/{r}/events.jsonl")]
    ends = sorted(e["t"] for e in ev if e["event"] == "rollout_done")
    c = [json.loads(l)["t"] for f in glob.glob(f"traces/{r}/*/*/chat.jsonl") for l in open(f)]
    live = lambda t: 128 - sum(x <= t for x in ends)
    by = {}
    for t in c:
        n = live(t["llm_start"])
        by.setdefault(min(n // 16 * 16, 112), []).append(t["llm_end"] - t["llm_start"])
    print(r, " | ".join(f"{k}-{k + 15} live: {st.median(v):5.1f} s ({len(v)})" for k, v in sorted(by.items(), reverse=True)))
