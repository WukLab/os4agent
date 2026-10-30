import glob, json, statistics as st, sys
for r in sys.argv[1:]:
    c = [json.loads(l) for f in glob.glob(f"traces/{r}/*/*/chat.jsonl") for l in open(f)]
    t0 = min(x["t"]["llm_start"] for x in c)
    early = [x for x in c if x["t"]["llm_start"] - t0 < 6 * 60]  # same window for both runs
    m = lambda k: st.median(k(x) for x in early)
    inval = sum(x['action'].get('action') == 'invalid' for x in early)
    print(f"{r:20} calls in first 6 min {len(early)} (invalid {100 * inval / len(early):.0f}%): latency {m(lambda x: x['t']['llm_end'] - x['t']['llm_start']):.1f} s, "
          f"output tokens {m(lambda x: x['completion_tokens']):.0f}, prompt tokens {m(lambda x: x['prompt_tokens']):.0f}, "
          f"tok/s {m(lambda x: x['completion_tokens'] / max(x['t']['llm_end'] - x['t']['llm_start'], 1e-3)):.1f}")
