import glob, json, statistics as st, sys
for r in sys.argv[1:]:
    c = [json.loads(l) for f in glob.glob(f"traces/{r}/*/*/chat.jsonl") for l in open(f)]
    tok = [x["completion_tokens"] for x in c]
    lat = [x["t"]["llm_end"] - x["t"]["llm_start"] for x in c]
    q = lambda v, p: sorted(v)[int(p * (len(v) - 1))]
    print(f"{r:20} calls {len(c)}: output tokens median {st.median(tok):.0f} (p10 {q(tok, .1)}, p90 {q(tok, .9)}), "
          f"forced {100 * sum('I have thought enough' in x['response'] for x in c) / len(c):.0f}%, "
          f"latency median {st.median(lat):.1f} s, tok/s {sum(tok) / sum(lat):.1f}")
