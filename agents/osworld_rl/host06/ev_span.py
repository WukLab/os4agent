import collections, json, sys, time
ev = [json.loads(l) for l in open(f"{sys.argv[1]}/events.jsonl")]
t0 = ev[0]["t"]
d = [e for e in ev if e["event"] == "rollout_done"]
print("first event", time.strftime("%T", time.localtime(t0)), "last", time.strftime("%T", time.localtime(ev[-1]["t"])),
      f"span {(ev[-1]['t'] - t0) / 60:.1f} min")
print("rollouts done", len(d), "errors", collections.Counter((e.get("error") or "")[:60] for e in d).most_common(3))
print("solved", sum(e["reward"] > 0 for e in d), "steps", [e["steps"] for e in d][:22])
