"""Share of model calls that ran out of the 1024-token thinking budget, and invalid actions among them, per epoch."""
import glob, json
for e, d in [("e1", "rec128_shot"), ("e2", "rec128e2_shot"), ("e3", "rec128e3_shot"), ("e4", "rec128e4_shot"), ("e5", "rec128e5_shot")]:
    n = over = inv = inv_over = 0
    for f in glob.glob(f"traces/{d}/*/*__g*/chat.jsonl"):
        for c in map(json.loads, open(f)):
            if "completion_tokens" not in c:
                continue
            n += 1
            o = c["completion_tokens"] >= 1024
            bad = (c.get("action") or {}).get("action") == "invalid"
            over += o; inv += bad; inv_over += bad and o
    print(f"{e}: model calls {n}, over the 1024-token thinking budget {over} ({over / n:.0%}), invalid actions {inv} ({inv_over} of them over budget)")
