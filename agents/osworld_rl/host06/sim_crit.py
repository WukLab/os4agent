"""In-place speculation (fork = undo copy, guess runs on the real desktop) applied from step 3 for WHOLE rollouts of
selected tasks, not just the tail. Same hit model as sim_inplace.py. Tasks ranked by median rollout time in reg e0+e1
(the history). Model times as recorded in reg e2 (first-wave calls are slower, so a hit hides more)."""
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
    task = os.path.basename(d).split("__g")[0]
    tm = json.load(open(f"{d}/timing.json"))
    chat = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
    steps = [json.loads(l) for l in open(f) if l.strip()]
    rows = [(c["t"]["llm_end"] - c["t"]["llm_start"], s["exec_s"]) for c, s in zip(chat, steps) if "exec_s" in s]
    rolls.append((task, tm["t_start"], tm["t_eval"], rows))
t0 = min(r[1] for r in rolls)
base = max(r[2] for r in rolls) - t0
def sim(tasks, fork, p_spec, seed, p_hit=0.61):
    rng, out = random.Random(seed), []
    for task, start, end, rows in rolls:
        delta = 0.0
        if task in tasks:
            for i, (m, e) in enumerate(rows):
                if i >= 2 and rng.random() < p_spec and rng.random() < p_hit:
                    delta += e - max(0.0, fork + e - m)
        out.append(end - delta)
    return max(out) - t0
print(f"reg e2 (step-only): {base / 60:.1f} min; slowest tasks in e0-e1: {[t[:8] for t in rank[:4]]}")
for n in (3, 5, 16):
    for fork in (10.6, 3.0):
        v = st.median(sim(set(rank[:n]), fork, 0.9, s) for s in range(30))
        print(f"top {n:2} slowest tasks ({8 * n:3} rollouts), whole rollouts, fork {fork:4} s -> {v / 60:.1f} min ({100 * (1 - v / base):+.1f}%)")
