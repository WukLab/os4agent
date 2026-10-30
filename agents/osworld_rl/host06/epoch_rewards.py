"""Mean reward per run (rollouts with an env error count as 0, as in training).  python3 epoch_rewards.py NAME=DIR ..."""
import json, sys
for arg in sys.argv[1:]:
    name, d = arg.split("=", 1)
    try:
        ev = [json.loads(l) for l in open(f"{d}/events.jsonl")]
        c = json.load(open(f"{d}/config.json"))
    except OSError:
        print(f"{name:22s} missing")
        continue
    r = [e["reward"] for e in ev if e["event"] == "rollout_done"]
    print(f"{name:22s} mean {sum(r) / len(r):.3f}  solved {sum(x > 0 for x in r)}/{len(r)}  model {c.get('model')}  "
          f"cache {c.get('screen_cache', 0)}  spec {c.get('spec')}  replay {bool(c.get('replay'))}")
