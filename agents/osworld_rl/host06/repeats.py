"""How often rollouts repeat the same action (same action key: type + target role|name + argument) step after step.
Per rollout: share of steps equal to the previous step, longest run of one identical action, and per task."""
import glob, json, os, statistics as st, sys
sys.path.insert(0, ".")
from toolspec.online import web_step
for r in sys.argv[1:]:
    per_task, rolls = {}, []
    for f in glob.glob(f"traces/{r}/*/*/traj.jsonl"):
        d = f.rsplit("/", 1)[0]
        keys = [web_step(d, s)[1] for s in (json.loads(l) for l in open(f) if l.strip()) if "action_timestamp" in s]
        if len(keys) < 2:
            continue
        rep = sum(a == b and a is not None for a, b in zip(keys, keys[1:])) / (len(keys) - 1)
        run = best = 1
        for a, b in zip(keys, keys[1:]):
            run = run + 1 if (a == b and a is not None) else 1
            best = max(best, run)
        task = os.path.basename(d).split("__g")[0][:8]
        rolls.append((rep, best, len(keys), task))
        per_task.setdefault(task, []).append((rep, best))
    n = len(rolls)
    print(f"== {r}: {n} rollouts")
    print(f"   steps that repeat the previous action: {100 * st.mean(x[0] for x in rolls):.0f}% on average")
    for k in (3, 5, 10):
        print(f"   rollouts with the same action >= {k:2} times in a row: {sum(x[1] >= k for x in rolls):3} ({100 * sum(x[1] >= k for x in rolls) / n:.0f}%)")
    print("   per task (repeat share / longest run, median):",
          ", ".join(f"{t} {100 * st.median(a for a, _ in v):.0f}%/{st.median(b for _, b in v):.0f}" for t, v in sorted(per_task.items(), key=lambda kv: -st.median(a for a, _ in kv[1]))))
