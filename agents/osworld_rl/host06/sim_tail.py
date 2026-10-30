"""Tail-only effect (time from the 64th rollout's last step to the last rollout's last step) on reg e2's trace.
In-place speculation on tail steps: covered w.p. COV, hit w.p. HIT; hit wait = max(0, FREEZE + env - model) instead of
env. PAUSE: seconds removed from every tail env step (OSWorld's fixed 2 s sleep). 30 seeds, median."""
import glob, json, random, statistics as st
R = "grpo_think_reg_e2"
rolls = []
for f in glob.glob(f"traces/{R}/*/*/traj.jsonl"):
    d = f.rsplit("/", 1)[0]
    tm = json.load(open(f"{d}/timing.json"))
    chat = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
    steps = [json.loads(l) for l in open(f) if l.strip()]
    rows = [(c["t"]["llm_end"] - c["t"]["llm_start"], s["exec_s"], c["t"]["llm_end"]) for c, s in zip(chat, steps) if "exec_s" in s]
    rolls.append((tm["t_eval"], rows))
t64 = sorted(r[0] for r in rolls)[63]
base_tail = max(r[0] for r in rolls) - t64
def tail(cov, hit, freeze, pause, seed):
    rng, out = random.Random(seed), []
    for end, rows in rolls:
        delta = 0.0
        for i, (m, e, t_end) in enumerate(rows):
            if t_end <= t64:
                continue
            e2 = max(0.5, e - pause)
            delta += e - e2
            if i >= 2 and rng.random() < cov and rng.random() < hit:
                delta += e2 - max(0.0, freeze + e2 - m)
        out.append(end - delta)
    return max(out) - t64
print(f"reg e2 tail: {base_tail / 60:.2f} min")
for label, cov, hit, fz, pause in [
        ("today's in-place (cap 10, top-1)", 0.6, 0.47, 13.0, 0),
        ("1: every tail step speculated", 1.0, 0.47, 10.6, 0),
        ("1+2: + repeat-last-action guess", 1.0, 0.65, 10.6, 0),
        ("3: no 2 s pause only", 0.0, 0.0, 10.6, 2),
        ("1+2+3", 1.0, 0.65, 10.6, 2),
        ("1+2+3 + tfork early-unfreeze (freeze 3 s)", 1.0, 0.65, 3.0, 2)]:
    v = st.median(tail(cov, hit, fz, pause, s) for s in range(30))
    print(f"{label:45} tail {v / 60:.2f} min ({100 * (1 - v / base_tail):+.1f}%)")
