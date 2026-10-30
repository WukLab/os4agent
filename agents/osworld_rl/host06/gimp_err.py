import json
for r in ("A8", "B8", "B8b", "B8c"):
    try:
        ev = [json.loads(l) for l in open(f"traces/spec_tail_{r}/events.jsonl")]
    except OSError:
        continue
    d = [e for e in ev if e.get("event") == "rollout_done"]
    bad = [e for e in d if e.get("error")]
    print(f"{r}: rollouts {len(d)}, errors {len(bad)}: " + "; ".join(f"{e['task'][:8]} k{e['k']} {str(e['error'])[:70]}" for e in bad))
