import json, glob, statistics as st
lat, tok = [], []
for f in glob.glob("/mnt/ssd2/vikranth/osworld/traces/rec32v2_tfork/*/*__g*/chat.jsonl"):
    for l in open(f):
        d = json.loads(l); t = d.get("t") or {}
        if "llm_start" in t: lat.append(t["llm_end"] - t["llm_start"]); tok.append((d.get("prompt_tokens", 0), d.get("completion_tokens", 0)))
lat.sort(); q = lambda p: lat[int(p * (len(lat) - 1))]
print(f"model calls: {len(lat)}  latency median {q(.5):.2f}s  p10 {q(.1):.2f}s  p90 {q(.9):.2f}s  min {lat[0]:.2f}s")
print(f"prompt tokens median {st.median(p for p, _ in tok):.0f}, completion tokens median {st.median(c for _, c in tok):.0f}")
print(f"one 49 ms round trip = {0.049 / q(.5) * 100:.1f}% of the median call")
