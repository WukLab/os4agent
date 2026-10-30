import json, sys, collections
ev = [json.loads(l) for l in open(f"{sys.argv[1]}/events.jsonl")]
done = [e for e in ev if e.get("event") == "rollout_done"]
print(f"rollouts {len(done)}, with error {sum(bool(e.get('error')) for e in done)}, steps per rollout {dict(collections.Counter(e['steps'] for e in done))}")
for e in done:
    if e.get("error"):
        print("  ", e["task"][:8], e["k"], str(e["error"])[-200:])
print("group errors:", [e.get("error", "")[-150:] for e in ev if e.get("event") == "group_error"])
sp = [e for e in ev if e.get("event") == "spec_exec" and e.get("error")]
for e in sp:
    print(f"  spec step with error: {e['task'][:8]} g{e['g']} hit={e['hit']} waited {e['waited_s']} s: {e['error'][-120:]}")
