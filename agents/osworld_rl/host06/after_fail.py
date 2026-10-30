import json, sys
ev = [json.loads(l) for l in open(f"{sys.argv[1]}/events.jsonl")]
t0 = ev[0]["t"]
for e in [e for e in ev if e.get("event") == "tfork_clone" and not e.get("ok", True)]:
    w = " ".join(e["why"]) if isinstance(e["why"], list) else str(e["why"])
    later = [x for x in ev if x.get("event") == "tfork_clone" and x.get("task") == e["task"] and x["t"] > e["t"]]
    print(f"{(e['t'] - t0) / 60:4.1f} min {e['task'][:8]}: {w[-90:]!r}\n     later forks in that group: {sum(x['ok'] for x in later)} ok, {sum(not x['ok'] for x in later)} failed")
