"""How rollouts end at a raised cap: solved / said done / cut by --stop-repeats / ran to the cap; vs a cap-15 baseline."""
import json, sys
run, base, cap = sys.argv[1], sys.argv[2], int(sys.argv[3])
ev = [json.loads(l) for l in open(f"traces/{run}/events.jsonl")]
cut = {(e["task"], e["k"]) for e in ev if e["event"] == "repeat_stop"}
done = [e for e in ev if e["event"] == "rollout_done"]
b = {}
for e in map(json.loads, open(f"traces/{base}/events.jsonl")):
    if e["event"] == "rollout_done": b.setdefault(e["task"], []).append((e["steps"], e["reward"] >= 0.9))
kinds = {}
for e in sorted(done, key=lambda e: e["task"]):
    ok = e["reward"] >= 0.9
    how = ("solved" if ok else "cut by repeats" if (e["task"], e["k"]) in cut else f"ran to {cap}" if e["steps"] >= cap else "said done, unsolved")
    kinds[how] = kinds.get(how, 0) + 1
    print(f"{e['task'][:8]} g{e['k']}: steps {e['steps']:2d} {how:20} {e['secs']/60:4.1f} min | cap-15 baseline {b.get(e['task'])}")
n = len(done)
print({k: f"{v}/{n}" for k, v in kinds.items()}, "| solved after step 15:", sum(1 for e in done if e["reward"] >= 0.9 and e["steps"] > 15))
t0 = ev[0]["t"]; d = sorted(e["t"] - t0 for e in done); end = d[-1]
print(f"finish times (min): {[round(x / 60, 1) for x in d]}")
print(f"epoch {end/60:.1f} min; after 50% done {100*(end-d[n//2-1])/end:.0f}%, after 75% {100*(end-d[int(n*.75)-1])/end:.0f}%")
