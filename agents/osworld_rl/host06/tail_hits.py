"""In reg e2's tail (model call ending after the 64th rollout's last step), how often would a guess have been right:
TAGE top-1 (online, warmed with reg e0-e1 like the runs), repeat-the-last-action, either of the two, TAGE top-2."""
import glob, json, sys
sys.path.insert(0, ".")
from toolspec.online import OnlineTage, web_step
tg = OnlineTage(2)
tg.warm([f"traces/grpo_think_reg_e{i}" for i in (0, 1)])
R = "grpo_think_reg_e2"
rolls, ends = [], []
for f in glob.glob(f"traces/{R}/*/*/traj.jsonl"):
    d = f.rsplit("/", 1)[0]
    chat = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
    steps = [json.loads(l) for l in open(f) if l.strip()]
    ends.append(json.load(open(f"{d}/timing.json"))["t_eval"])
    rolls.append((d, [(c["t"]["llm_start"], c["t"]["llm_end"], s) for c, s in zip(chat, steps)]))
t64 = sorted(ends)[63]
events = sorted((t0, t1, d, i, s) for d, rows in rolls for i, (t0, t1, s) in enumerate(rows))
last, n = {}, {"steps": 0, "top1": 0, "repeat": 0, "either": 0, "top2": 0}
for t0, t1, d, i, s in events:  # online in time order, like the run
    task, key = web_step(d, s)
    g = tg.decide(task, d)["guesses"][:2]
    tg.reveal_key(task, d, key)
    rep = last.get(d)
    if i >= 2 and t1 > t64 and key is not None:
        n["steps"] += 1
        n["top1"] += bool(g) and g[0] == key
        n["repeat"] += rep == key
        n["either"] += (bool(g) and g[0] == key) or rep == key
        n["top2"] += key in g
    last[d] = key
s = n["steps"]
print(f"tail steps {s}: TAGE top-1 {100 * n['top1'] / s:.0f}% | repeat-last {100 * n['repeat'] / s:.0f}% | "
      f"top-1 or repeat-last {100 * n['either'] / s:.0f}% | TAGE top-2 {100 * n['top2'] / s:.0f}%")
