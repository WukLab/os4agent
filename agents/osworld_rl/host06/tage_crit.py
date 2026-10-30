"""Would TAGE top-2 speculation speed up the recorded GRPO epochs? Per step: M = model s (llm_end - llm_start),
E = step + observe s (next obs - llm_end). No spec: M + E. Hit: max(M, F + E). Miss: M + max(0, F - M) + E (wait for
tfork's freeze). F = fork s. Spec only from step 3 and while < 64 rollouts are live. r scales M (longer reasoning)."""
import glob, json, os, sys, statistics as st
sys.path.insert(0, ".")
from toolspec.online import OnlineTage, web_step

F, FROM, BELOW = 3.0, 3, 999
THINK = {"chrome": [(8, 6.0), (32, 7.9), (64, 9.3), (128, 12.7)], "calc": [(8, 15.0), (32, 18.4), (64, 21.2), (128, 29.5)]}
def think_s(d, live):
    tab = THINK["calc" if "libreoffice_calc" in d else "chrome"]
    for (n0, t0), (n1, t1) in zip(tab, tab[1:]):
        if live <= n1:
            return t0 + (t1 - t0) * max(0, live - n0) / (n1 - n0)
    return tab[-1][1]
for r in ("think",):
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
        tg = OnlineTage(2); save, extra, per = {}, {}, {}
        for t0, d, n, task, key, M, E in steps:
            g = tg.decide(task, d)["guesses"][:2]
            tg.reveal_key(task, d, key)
            live = sum(a <= t0 < b for _, a, b in life)
            if r == "think":
                extra[d] = extra.get(d, 0) + think_s(d, live) - M
                M = think_s(d, live)
            b0 = tot["spec"]
            tot["base"] += M + E
            tot["n"] += 1
            per.setdefault(d, []).append((M, E, key in g and n >= FROM))
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
        end = lambda d, b, sv: b + extra.get(d, 0) - sv * save.get(d, 0)
        for sv in (0, 1):
            d, a0, b = max(life, key=lambda x: end(x[0], x[2], sv))
            st_ = per.get(d, [])
            print(f"  e{e} {'spec  ' if sv else 'nospec'} last rollout {d.split('/')[-2][:5]}/{d.split('/')[-1][:8]}: starts {(a0-t0)/60:4.1f} min in, "
                  f"{len(st_)} steps, model {sum(x[0] for x in st_)/60:4.1f} + env {sum(x[1] for x in st_)/60:4.1f} min, hits {sum(x[2] for x in st_)}, "
                  f"saved {save.get(d,0)/60:4.1f} min -> epoch {(end(d,b,sv)-t0)/60:4.1f} min")
        wall[0] += max(b + extra.get(d, 0) for d, _, b in life) - t0
        wall[1] += max(b + extra.get(d, 0) - save.get(d, 0) for d, _, b in life) - t0
    print(f"epoch wall (sum of 10, no-spec -> spec) {wall[0]/60:.0f} -> {wall[1]/60:.0f} min ({100*(1-wall[1]/wall[0]):.1f}% less)")
    print(f"model {r}: {tot['n']} steps, speculated {100*tot['spec_n']/tot['n']:.0f}%, top-2 hit {100*tot['hit']/max(tot['spec_n'],1):.0f}%; "
          f"step time {tot['base']/3600:.1f} h -> {tot['spec']/3600:.1f} h ({100*(1-tot['spec']/tot['base']):.1f}% less), "
          f"saved per speculated step {(tot['base']-tot['spec'])/max(tot['spec_n'],1):.1f} s")
