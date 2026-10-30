"""Longer tails: reg e2's rollouts that hit the 15-step cap continue to S steps (extra steps drawn from that rollout's
own (model, env) times). Model time x k. Tail = after the 64th rollout's last step; speculated w.p. 0.64, hit w.p. 0.71;
a hit's wait after the model = max(0, 10.6 + env + 13 - model). Epoch = latest rollout end (step-only). 30 seeds."""
import glob, json, random, statistics as st
R, FORK, OVER, P_SPEC, P_HIT = "grpo_think_reg_e2", 10.6, 13.0, 0.64, 0.71
base_rolls = []
for f in glob.glob(f"traces/{R}/*/*/traj.jsonl"):
    d = f.rsplit("/", 1)[0]
    tm = json.load(open(f"{d}/timing.json"))
    chat = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
    steps = [json.loads(l) for l in open(f) if l.strip()]
    rows = [(c["t"]["llm_end"] - c["t"]["llm_start"], s["exec_s"]) for c, s in zip(chat, steps) if "exec_s" in s]
    base_rolls.append((tm["t_start"], rows, len(steps) >= 15))
t0 = min(r[0] for r in base_rolls)
def run(S, k, spec, seed):
    rng = random.Random(seed)
    rolls = []
    for start, rows, capped in base_rolls:
        rows = list(rows) + ([rng.choice(rows) for _ in range(S - len(rows))] if capped and S > len(rows) else [])
        rolls.append((start, rows))
    # timeline per rollout: start + sum(model*k + env); spec decided once the 64th rollout is done
    plain_end = sorted(start - t0 + sum(m * k + e for m, e in rows) for start, rows in rolls)
    t64 = plain_end[63]
    out = []
    for start, rows in rolls:
        t = start - t0
        for i, (m, e) in enumerate(rows):
            t += m * k
            if spec and i >= 2 and t > t64 and rng.random() < P_SPEC and rng.random() < P_HIT:
                t += max(0.0, FORK + e + OVER - m * k)
            else:
                t += e
        out.append(t)
    return max(out), t64
for k in (1, 2):
    for S in (15, 20, 30):
        reg = [run(S, k, False, s) for s in range(30)]
        sp = [run(S, k, True, s) for s in range(30)]
        r, s_ = st.median(x[0] for x in reg), st.median(x[0] for x in sp)
        t64 = st.median(x[1] for x in reg)
        print(f"model x{k}, max {S} steps: reg {r / 60:5.1f} min (tail {(r - t64) / 60:4.1f} = {100 * (r - t64) / r:3.0f}%) -> spec {s_ / 60:5.1f} min ({100 * (1 - s_ / r):+.1f}%)")
