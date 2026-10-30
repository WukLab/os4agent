import json, glob, sys
rows = [json.loads(l) for f in glob.glob(f"{sys.argv[1]}/*/*/chat.jsonl") for l in open(f)]
think = sum("</think>" in r["response"] for r in rows)
forced = sum("I have thought enough" in r["response"] for r in rows)
inval = sum(r["action"].get("action") == "invalid" for r in rows)
lat = sorted(r["t"]["llm_end"] - r["t"]["llm_start"] for r in rows)
tok = sorted(r["completion_tokens"] for r in rows)
print(f"{len(rows)} model calls: with </think> {think}, forced {forced}, invalid {inval}, "
      f"latency median {lat[len(lat) // 2]:.1f} s max {lat[-1]:.1f} s, output tokens median {tok[len(tok) // 2]}")
print("reasoning prompt in system:", "Think step by step" in rows[0]["messages"][0]["content"])
