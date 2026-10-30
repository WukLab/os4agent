"""Offline hit rate of each environment-side policy on each recorded GRPO epoch, using only the earlier epochs as history
(as a real run would have them). No desktops run.

  python offline_hits.py E1 E2 E3 ...        (trace dirs in epoch order; epoch k is scored with epochs 1..k-1)

  speculation   TAGE (toolspec.online.OnlineTage) warmed on the earlier epochs, updated online as this epoch's steps
                happen (time order): top-1 guess of the next action = the action taken
  screen cache  (task, screen, action) seen before -> served; counted only if the cached next screen equals the real one
  history cache (task, exact action history) seen before -> served; counted only if the next screen matches
  prefix tree   policy 2 (teammate's in-memory tree, history keys, depth 8, no check): hits as the tree serves them
The three caches come from prefix_sim.py (same assumptions; see its docstring).
"""
import datetime as dt, glob, json, os, re, subprocess, sys

sys.path[:0] = ["/mnt/ssd2/vikranth/osworld"]
from toolspec.online import OnlineTage, web_step  # noqa: E402

epochs = sys.argv[1:]


def spec_hit(prev, cur):
    sp = OnlineTage(topk=8)
    sp.warm(prev)
    steps = []
    for d in glob.glob(f"{cur}/*/*__g*"):
        p = f"{d}/traj.jsonl"
        if not os.path.exists(p):
            continue
        for s in map(json.loads, open(p)):
            if "action_timestamp" in s:
                steps.append((s["action_timestamp"], d, s.get("step_num", 0), s))
    steps.sort(key=lambda x: (x[0], x[1], x[2]))
    for _, d, _, s in steps:
        task, key = web_step(d, s)
        sp.decide(task, d)
        sp.reveal_key(task, d, key)
    m = sp.summary()
    return m["hit1_pct"], m["decisions"]


def sim(prev, cur, *extra):
    out = subprocess.run([sys.executable, "/mnt/ssd2/vikranth/osworld/prefix_sim.py", ",".join(prev), cur, "--pool", "0", *extra],
                         capture_output=True, text=True).stdout
    return out


def hits(line):
    m = re.search(r"hit (\d+)% of steps", line)
    return int(m.group(1)) if m else None


print("| epoch (history) | speculation: TAGE top-1 | screen cache | history cache | prefix tree (policy 2, unchecked) |")
print("|---|---|---|---|---|")
for k in range(1, len(epochs)):
    prev, cur = epochs[:k], epochs[k]
    s1, n = spec_hit(prev, cur)
    scr = [l for l in sim(prev, cur, "--key", "screen").splitlines() if l.startswith("eager")][0]
    his = [l for l in sim(prev, cur, "--key", "prefix").splitlines() if l.startswith("eager")][0]
    tre = [l for l in sim(prev, cur, "--key", "prefix", "--tree-depth", "8", "--validate", "0").splitlines() if l.startswith("lazy")][0]
    name = lambda p: os.path.basename(p.rstrip("/"))
    print(f"| {name(cur)} ({len(prev)} earlier) | {s1:.0f}% of {n} steps | {hits(scr)}% | {hits(his)}% | {hits(tre)}% |", flush=True)
