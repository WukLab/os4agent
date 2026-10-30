"""Would TAGE top-2 speculation speed up the recorded GRPO epochs? Per step: M = model s (llm_end - llm_start),
E = step + observe s (next obs - llm_end). No spec: M + E. Hit: max(M, F + E). Miss: M + max(0, F - M) + E (wait for
tfork's freeze). F = fork s. Spec only from step 3 and while < 64 rollouts are live. r scales M (longer reasoning)."""
import glob, json, os, sys, statistics as st
sys.path.insert(0, ".")
from toolspec.online import OnlineTage, web_step

F, FROM, BELOW = float(sys.argv[1]) if sys.argv[1:] else 3.0, 3, 64
for r in (1, 2, 3, 4):
    tot = {"base": 0.0, "spec": 0.0, "n": 0, "spec_n": 0, "hit": 0}; wall = [0.0, 0.0]
    for e in range(10):
        steps, life = [], []
        for d in glob.glob(f"traces/grpo_tfork16_e{e}/*/*__g*"):
            if not (os.path.exists(f"{d}/traj.jsonl") and os.path.exists(f"{d}/chat.jsonl")):
                continue
            traj = [json.loads(l) for l in open(f"{d}/traj.jsonl") if l.strip()]
            traj = [s for s in traj if "action_timestamp" in s]
            chat = [json.loads(l)["t"] for l in open(f"{d}/chat.jsonl")]
            if not chat: continue
            life.append((d, chat[0]["obs"], chat[-1]["llm_end"] + traj[-1].get("exec_s", 0) if traj else chat[-1]["llm_end"]))
            for i, s in enumerate(traj[:len(chat)]):
                t = chat[i]
                M = t["llm_end"] - t["llm_start"]
                E = (chat[i + 1]["obs"] - t["llm_end"]) if i + 1 < len(chat) else s.get("exec_s", 0)
                steps.append((t["llm_start"], d, i + 1, *web_step(d, s), M, E))
        steps.sort()
        tg = OnlineTage(2); save, extra = {}, {}
        for t0, d, n, task, key, M, E in steps:
            g = tg.decide(task, d)["guesses"][:2]
            tg.reveal_key(task, d, key)
            M *= r; extra[d] = extra.get(d, 0) + M * (1 - 1 / r)
            live = sum(a <= t0 < b for _, a, b in life)
            b0 = tot["spec"]
            tot["base"] += M + E
            tot["n"] += 1
            if n >= FROM and live < BELOW and g:
                tot["spec_n"] += 1
                if key in g:
                    tot["hit"] += 1
                    tot["spec"] += max(M, F + E)
                else:
                    tot["spec"] += M + max(0.0, F - M) + E
            else:
                tot["spec"] += M + E
            save[d] = save.get(d, 0) + (M + E) - (tot["spec"] - b0)
        t0 = min(a for _, a, _ in life)
        wall[0] += max(b + extra.get(d, 0) for d, _, b in life) - t0
        wall[1] += max(b + extra.get(d, 0) - save.get(d, 0) for d, _, b in life) - t0
    print(f"epoch wall (sum of 10, no-spec -> spec) {wall[0]/60:.0f} -> {wall[1]/60:.0f} min ({100*(1-wall[1]/wall[0]):.1f}% less)")
    print(f"reasoning x{r}: {tot['n']} steps, speculated {100*tot['spec_n']/tot['n']:.0f}%, top-2 hit {100*tot['hit']/max(tot['spec_n'],1):.0f}%; "
          f"step time {tot['base']/3600:.1f} h -> {tot['spec']/3600:.1f} h ({100*(1-tot['spec']/tot['base']):.1f}% less), "
          f"saved per speculated step {(tot['base']-tot['spec'])/max(tot['spec_n'],1):.1f} s")
