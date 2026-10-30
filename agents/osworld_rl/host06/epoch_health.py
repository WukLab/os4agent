"""Per epoch: rollout errors, invalid actions, step counts, action kinds, steps per task -- to tell policy change from
recording problems.  python3 epoch_health.py DIR ..."""
import collections, glob, json, os, sys
for root in sys.argv[1:]:
    ev = [json.loads(l) for l in open(f"{root}/events.jsonl")]
    done = [e for e in ev if e["event"] == "rollout_done"]
    errs = collections.Counter((e.get("error") or "")[:40] for e in done if e.get("error"))
    kinds, inval, n = collections.Counter(), 0, 0
    for f in glob.glob(f"{root}/*/*__g*/traj.jsonl"):
        for s in map(json.loads, open(f)):
            a = json.loads(s["action"]).get("action")
            kinds[a] += 1
            inval += a == "invalid"
            n += 1
    print(f"{os.path.basename(root)}: steps {n}, mean {n / len(done):.1f}/rollout, capped {sum(e['steps'] >= 20 for e in done)}, "
          f"solved {sum(e['reward'] > 0 for e in done)}, errors {sum(errs.values())} {dict(errs)}, invalid {inval} ({inval / n:.1%}), "
          f"top actions {kinds.most_common(5)}")
