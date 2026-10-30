import glob, json, statistics as st, sys
for r in sys.argv[1:]:
    ev = [json.loads(l) for l in open(f"traces/{r}/events.jsonl")]
    ends = sorted(e["t"] for e in ev if e["event"] == "rollout_done")
    c = [json.loads(l) for f in glob.glob(f"traces/{r}/*/*/chat.jsonl") for l in open(f)]
    first = [x for x in c if 128 - sum(t <= x["t"]["llm_start"] for t in ends) >= 112]
    m = lambda f: st.median(f(x) for x in first)
    lat = m(lambda x: x["t"]["llm_end"] - x["t"]["llm_start"])
    print(f"{r:20} first-wave calls {len(first)}: latency {lat:.1f} s, prompt tokens {m(lambda x: x['prompt_tokens']):.0f} "
          f"(mean {st.mean(x['prompt_tokens'] for x in first):.0f}), output {m(lambda x: x['completion_tokens']):.0f}, "
          f"total tokens per call (mean) {st.mean(x['prompt_tokens'] + x['completion_tokens'] for x in first):.0f}")
