import json, sys
for r in sys.argv[1:]:
    ev = [json.loads(l) for l in open(f"{r}/events.jsonl")]
    t0 = ev[0]["t"]
    m = lambda v: f"{(min(v) - t0) / 60:4.1f}" if v else "   -"
    print(r)
    for t in sorted({e["task"] for e in ev if e.get("event") == "fork"}):
        fail = [e["t"] for e in ev if e.get("event") == "tfork_clone" and not e.get("ok", True) and e.get("task") == t and "resolve parent" in str(e.get("why"))]
        done = [e["t"] for e in ev if e.get("event") == "rollout_done" and e.get("task") == t]
        spec = [e for e in ev if e.get("event") == "spec_exec" and e.get("task") == t]
        print(f"   {t[:8]}: first rollout done {m(done)} min, first parent failure {m(fail)} min, failures {len(fail):3}, "
              f"spec steps {len(spec):3}, hits {sum(e['hit'] is not None for e in spec):3}")
