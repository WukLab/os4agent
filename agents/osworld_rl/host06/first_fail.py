import json, sys
for r in ("B8", "B8b"):
    ev = [json.loads(l) for l in open(f"{r}/events.jsonl")]
    t0 = ev[0]["t"]
    print(r)
    for t in sorted({e["task"] for e in ev if e.get("event") == "fork"}):
        f = [e for e in ev if e.get("event") == "tfork_clone" and not e.get("ok", True) and e.get("task") == t]
        if not f:
            continue
        w = lambda e: (" ".join(e["why"]) if isinstance(e["why"], list) else str(e["why"]))
        first_parent = next((e for e in f if "resolve parent" in w(e)), None)
        before = [e for e in f if first_parent and e["t"] < first_parent["t"]]
        print(f"   {t[:8]}: failures before the first 'resolve parent': {len(before)}"
              + (f" -> first one at {(before[0]['t'] - t0) / 60:.1f} min: {w(before[0])[-110:]!r}" if before else "")
              + (f"; first 'resolve parent' at {(first_parent['t'] - t0) / 60:.1f} min" if first_parent else ""))
