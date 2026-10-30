"""Solved per task across recorded epochs: python3 epoch_rewards.py NAME=TRACE [NAME=TRACE ...]"""
import json, sys
runs = [(x.split("=", 1)[0], x.split("=", 1)[1]) for x in sys.argv[1:]]
tab, tot = {}, {}
for name, d in runs:
    try:
        ev = [json.loads(l) for l in open(f"{d}/events.jsonl")]
    except OSError:
        continue
    done = [e for e in ev if e["event"] == "rollout_done"]
    t0 = ev[0]["t"]
    for e in done:
        tab.setdefault(e["task"][:8], {}).setdefault(name, 0)
        tab[e["task"][:8]][name] += e["reward"] > 0
    tot[name] = (sum(e["reward"] > 0 for e in done), len(done), sum(bool(e.get("error")) for e in done),
                 (max(e["t"] for e in done) - t0) / 60 if done else 0)
names = [n for n, _ in runs if n in tot]
print("| task | " + " | ".join(names) + " |\n|---|" + "---|" * len(names))
for t in sorted(tab):
    print(f"| {t} | " + " | ".join(str(tab[t].get(n, "-")) for n in names) + " |")
print("| **solved** | " + " | ".join(f"**{tot[n][0]}/{tot[n][1]}**" for n in names) + " |")
print("| rollout errors | " + " | ".join(str(tot[n][2]) for n in names) + " |")
print("| epoch time (min) | " + " | ".join(f"{tot[n][3]:.1f}" for n in names) + " |")
