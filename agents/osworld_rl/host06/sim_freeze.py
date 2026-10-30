"""In-place speculation on reg e2's trace (step-only, recorded model + env times): who speculates x how long the fork
freezes the desktop. Hit (top-1, 0.61): result ready FREEZE + env after the step starts -> waits max(0, that - model).
Miss: backup takes over, normal env. 90% of eligible steps get a slot. Epoch = latest rollout end. 30 seeds."""
import glob, json, os, random, statistics as st
R = "grpo_think_reg_e2"
dur = {}
for p in glob.glob("traces/grpo_think_reg_e[01]/*/*__g*/timing.json"):
    t, tm = os.path.basename(os.path.dirname(p)).split("__g")[0], json.load(open(p))
    if tm.get("t_eval"): dur.setdefault(t, []).append(tm["t_eval"] - tm["t_start"])
rank = sorted(dur, key=lambda t: -st.median(dur[t]))
rolls = []
for f in glob.glob(f"traces/{R}/*/*/traj.jsonl"):
    d = f.rsplit("/", 1)[0]
    tm = json.load(open(f"{d}/timing.json"))
    chat = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
    steps = [json.loads(l) for l in open(f) if l.strip()]
    rows = [(c["t"]["llm_end"] - c["t"]["llm_start"], s["exec_s"], c["t"]["llm_end"]) for c, s in zip(chat, steps) if "exec_s" in s]
    rolls.append((os.path.basename(d).split("__g")[0], tm["t_start"], tm["t_eval"], rows))
t0 = min(r[1] for r in rolls)
t64 = sorted(r[2] for r in rolls)[63]
base = max(r[2] for r in rolls) - t0
def sim(tasks, freeze, tail_only, seed):
    rng, out = random.Random(seed), []
    for task, start, end, rows in rolls:
        delta = 0.0
        if tasks is None or task in tasks:
            for i, (m, e, t_end) in enumerate(rows):
                if i >= 2 and (not tail_only or t_end > t64) and rng.random() < 0.9 and rng.random() < 0.61:
                    delta += e - max(0.0, freeze + e - m)
        out.append(end - delta)
    return max(out) - t0
print(f"reg e2 step-only: {base / 60:.1f} min")
print(f"{'who speculates':38} {'freeze 10.6 s (today)':>22} {'3 s':>9} {'1.5 s':>9}")
for label, tasks, tail in [("tail only, all rollouts", None, True), ("3 slowest tasks, whole rollout", set(rank[:3]), False),
                           ("5 slowest tasks, whole rollout", set(rank[:5]), False), ("all rollouts, whole rollout", None, False)]:
    cells = []
    for fz in (10.6, 3.0, 1.5):
        v = st.median(sim(tasks, fz, tail, s) for s in range(30))
        cells.append(f"{v / 60:.1f} ({100 * (1 - v / base):+.1f}%)")
    print(f"{label:38} {cells[0]:>22} {cells[1]:>9} {cells[2]:>9}")
