"""Counterfactual: the regular epoch's own timeline, with speculation in its tail. Tail steps (model call ending after
the 64th rollout finished) become hits at the rate spec e0 measured; a hit saves that step's whole env time (measured
hit wait 0 s). Each rollout ends earlier by its savings; the epoch ends at the latest rollout."""
import glob, json, random, sys
hit_rate = float(sys.argv[2])
for r in sys.argv[1].split(","):
    ev = [json.loads(l) for l in open(f"traces/{r}/events.jsonl")]
    t0 = ev[0]["t"]
    done = sorted(e["t"] for e in ev if e["event"] == "rollout_done")
    t64 = done[63]
    res = []
    for seed in range(20):
        rng, ends = random.Random(seed), []
        for f in glob.glob(f"traces/{r}/*/*/traj.jsonl"):
            d = f.rsplit("/", 1)[0]
            tm = json.load(open(f"{d}/timing.json"))
            chat = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
            steps = [json.loads(l) for l in open(f) if l.strip()]
            save = sum(s["exec_s"] for i, s in enumerate(steps) if i < len(chat) and i >= 2 and chat[i]["t"]["llm_end"] > t64
                       and "exec_s" in s and rng.random() < hit_rate)
            ends.append(tm["t_end"] - save)
        res.append(max(ends) - t0)
    base = done[-1] - t0
    new = sorted(res)[len(res) // 2]
    print(f"{r}: wall {base / 60:.1f} min -> {new / 60:.1f} min ({100 * (1 - new / base):.1f}% faster), tail {(done[-1] - t64) / 60:.1f} -> {(new - (t64 - t0)) / 60:.1f} min")
