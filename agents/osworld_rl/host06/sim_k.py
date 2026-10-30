"""Would speculation pay with slower model calls? On reg e2's trace (step-only times), model time x k for every step.
Tail steps (model call ending after the 64th rollout's last step) are speculated with prob 0.64 and hit with prob 0.71
(spec e2). A hit's result is ready at fork 10.6 s + (env step + 13 s copy overhead) after the step starts; the rollout
waits max(0, that - model) after the model, instead of the normal env time. Epoch = latest rollout end. Median of 30 seeds."""
import glob, json, random, statistics as st
R, FORK, OVER, P_SPEC, P_HIT = "grpo_think_reg_e2", 10.6, 13.0, 0.64, 0.71
rolls = []
for f in glob.glob(f"traces/{R}/*/*/traj.jsonl"):
    d = f.rsplit("/", 1)[0]
    tm = json.load(open(f"{d}/timing.json"))
    chat = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
    steps = [json.loads(l) for l in open(f) if l.strip()]
    rows = [(c["t"]["llm_end"] - c["t"]["llm_start"], s["exec_s"], c["t"]["llm_end"]) for c, s in zip(chat, steps) if "exec_s" in s]
    rolls.append((tm["t_start"], tm["t_eval"], rows))
t0 = min(r[0] for r in rolls)
ends = sorted(r[1] for r in rolls)
t64 = ends[63]
for k in (1, 1.5, 2, 2.5, 3):
    base = max(r[1] + (k - 1) * sum(m for m, _, _ in r[2]) for r in rolls) - t0  # reg at model x k
    res = []
    for seed in range(30):
        rng, out = random.Random(seed), []
        for start, end, rows in rolls:
            end_k = end + (k - 1) * sum(m for m, _, _ in rows)
            delta = 0.0
            for i, (m, e, t_end) in enumerate(rows):
                if i >= 2 and t_end > t64 and rng.random() < P_SPEC and rng.random() < P_HIT:
                    wait = max(0.0, FORK + e + OVER - m * k)
                    delta += e - wait  # positive = saved
            out.append(end_k - delta)
        res.append(max(out) - t0)
    spec = st.median(res)
    tail_m = st.median([m * k for r in rolls for (m, _, t) in r[2] if t > t64])
    print(f"model x{k}: tail model call ~{tail_m:4.0f} s | reg {base / 60:5.1f} min -> spec {spec / 60:5.1f} min  ({100 * (1 - spec / base):+.1f}%)")
