"""TAGE next-action accuracy per GRPO epoch, as speculation would see it (offline, traj.jsonl only).

  venv/bin/python tage_epochs.py EPOCH1_DIR EPOCH2_DIR EPOCH3_DIR ...

For epoch e: TAGE is warmed on a set of earlier epochs, then fed epoch e step by step in recorded time order; before
each step it guesses (top-1, top-2) and is scored against the action taken, then learns it -- as OnlineTage does in a
run. Warm sets: none (cold), the previous epoch only, all earlier epochs. Also split by step depth.
"""
import json, os, sys
from collections import defaultdict

sys.path[:0] = ["/mnt/ssd2/vikranth/osworld"]
from toolspec.online import OnlineTage, web_step  # noqa: E402
import glob  # noqa: E402

epochs = sys.argv[1:]


def steps_of(root):
    out = []
    for d in glob.glob(os.path.join(root, "*", "*__g*")):
        p = os.path.join(d, "traj.jsonl")
        if not os.path.exists(p):
            continue
        for s in map(json.loads, (l for l in open(p) if l.strip())):
            if "action_timestamp" in s:
                task, key = web_step(d, s)
                out.append((s["action_timestamp"], d, s.get("step_num", 0), task, key))
    return sorted(out)


def score(warm, cur):
    t = OnlineTage(8)
    if warm:
        t.warm(warm)
    hist = defaultdict(list)
    n = h1 = h2 = 0
    by_depth = defaultdict(lambda: [0, 0])
    for _, d, step, task, key in steps_of(cur):
        if key is None:
            continue
        g = t.tage.predict(task, hist[d])[0]
        n += 1
        h1 += bool(g) and g[0] == key
        h2 += key in g[:2]
        b = "1-3" if step <= 3 else "4-10" if step <= 10 else "11-20"
        by_depth[b][0] += 1
        by_depth[b][1] += bool(g) and g[0] == key
        t.tage.update(task, hist[d], key)
        hist[d].append(key)
    return n, h1 / n, h2 / n, {b: v[1] / v[0] for b, v in by_depth.items()}


print(f"{'epoch':8s} {'warmed on':28s} {'steps':>6s} {'top-1':>6s} {'top-2':>6s}   top-1 by step: 1-3 / 4-10 / 11-20")
for e, cur in enumerate(epochs, 1):
    sets = [("none (cold)", [])]
    if e >= 2:
        sets.append(("previous epoch only", [epochs[e - 2]]))
    if e >= 3:
        sets.append((f"all earlier (epochs 1-{e - 1})", epochs[:e - 1]))
    for name, warm in sets:
        n, h1, h2, bd = score(warm, cur)
        print(f"epoch {e}  {name:28s} {n:6d} {h1:6.1%} {h2:6.1%}   "
              f"{bd.get('1-3', 0):.0%} / {bd.get('4-10', 0):.0%} / {bd.get('11-20', 0):.0%}")
