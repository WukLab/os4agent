"""Speculate in place: fork once (the undo copy), then run TAGE's top guess on the real desktop. On reg e2's trace
(step-only), model time as recorded. Tail steps speculated w.p. P_SPEC, hit w.p. 0.61 (top-1). Hit: result ready
FORK + env after the step starts -> rollout waits max(0, FORK + env - model) instead of env. Miss: backup copy (ready
at FORK + fixups, during the model call) runs the real action: env as normal (+ MISS_EXTRA). Epoch = latest end. 30 seeds."""
import glob, json, random, statistics as st
R = "grpo_think_reg_e2"
rolls = []
for f in glob.glob(f"traces/{R}/*/*/traj.jsonl"):
    d = f.rsplit("/", 1)[0]
    tm = json.load(open(f"{d}/timing.json"))
    chat = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
    steps = [json.loads(l) for l in open(f) if l.strip()]
    rows = [(c["t"]["llm_end"] - c["t"]["llm_start"], s["exec_s"], c["t"]["llm_end"]) for c, s in zip(chat, steps) if "exec_s" in s]
    rolls.append((tm["t_start"], tm["t_eval"], rows))
t0 = min(r[0] for r in rolls)
t64 = sorted(r[1] for r in rolls)[63]
base = max(r[1] for r in rolls) - t0
def sim(fork, p_spec, p_hit, miss_extra, seed):
    rng, out = random.Random(seed), []
    for start, end, rows in rolls:
        delta = 0.0
        for i, (m, e, t_end) in enumerate(rows):
            if i >= 2 and t_end > t64 and rng.random() < p_spec:
                delta += (e - max(0.0, fork + e - m)) if rng.random() < p_hit else -miss_extra
        out.append(end - delta)
    return max(out) - t0
print(f"reg e2 (step-only): {base / 60:.1f} min")
for label, fork, p_spec, miss in [("today's fork 10.6 s, 64% of tail steps speculated", 10.6, 0.64, 0),
                                  ("today's fork, 90% speculated (1 copy per step -> more steps fit the cap)", 10.6, 0.90, 0),
                                  ("today's fork, 90%, miss costs +3 s", 10.6, 0.90, 3),
                                  ("tfork unfreeze-early (fork ~3 s), 90% speculated", 3.0, 0.90, 0)]:
    v = st.median(sim(fork, p_spec, 0.61, miss, s) for s in range(30))
    print(f"{label:72} -> {v / 60:.1f} min ({100 * (1 - v / base):+.1f}%)")
