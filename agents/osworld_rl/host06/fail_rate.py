import json, sys
for r in sys.argv[1:]:
    try:
        ev = [json.loads(l) for l in open(f"traces/{r}/events.jsonl")]
    except OSError:
        continue
    c = [e for e in ev if e.get("event") == "tfork_clone"]
    w = lambda e: " ".join(e["why"]) if isinstance(e.get("why"), list) else str(e.get("why") or "")
    bad = [e for e in c if not e["ok"]]
    casc = [e for e in bad if "resolve parent" in w(e)]
    print(f"{r:16} clones {len(c):4}, failed {len(bad):3} ({100 * len(bad) / max(len(c), 1):4.1f}%), of which cascade {len(casc):3}, ordinary {len(bad) - len(casc):2} ({100 * (len(bad) - len(casc)) / max(len(c), 1):.1f}%)")
