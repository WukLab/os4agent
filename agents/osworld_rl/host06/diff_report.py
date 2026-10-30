"""Rollout length vs task difficulty for a run: per task and per difficulty (scout_candidates.tsv), share finishing
before the cap, and the share of the epoch after half the rollouts finished (one wave), at the cap and if cap-hitters
kept stepping at the same rate to 30/50 steps."""
import json, sys, statistics as st
run, cap = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 15
diff = {l.split("\t")[1]: l.split("\t")[2] for l in open("scout_candidates.tsv") if "\t" in l}
R = [e for e in map(json.loads, open(f"traces/{run}/events.jsonl")) if e["event"] == "rollout_done"]
by = {}
for e in R:
    by.setdefault(e["task"], []).append(e)
print(f"{'task':10} {'diff':6} {'ok':>4} {'steps':>12} {'min':>5}")
for t, es in sorted(by.items(), key=lambda kv: ["easy", "medium", "hard"].index(diff.get(kv[0], "hard"))):
    print(f"{t[:8]:10} {diff.get(t, '?'):6} {sum(e['reward'] >= 0.9 for e in es)}/{len(es):<2} {str(sorted(e['steps'] for e in es)):>12} "
          f"{st.median(e['secs'] for e in es) / 60:5.1f}")
for d in ("easy", "medium", "hard"):
    es = [e for e in R if diff.get(e["task"]) == d]
    if es:
        print(f"{d:6}: {len(es)} rollouts, solved {sum(e['reward'] >= 0.9 for e in es)}, median steps {st.median(e['steps'] for e in es)}, "
              f"before cap {sum(e['steps'] < cap for e in es)}/{len(es)}, median {st.median(e['secs'] for e in es) / 60:.1f} min")
early = sum(e["steps"] < cap for e in R)
print(f"all: {len(R)} rollouts, finishing before the cap {early}/{len(R)} ({100 * early / len(R):.0f}%)")
for c in (cap, 30, 50):
    d = sorted(e["secs"] * (c / cap if e["steps"] >= cap else 1) for e in R)
    print(f"  cap {c:3d}: epoch {d[-1] / 60:5.1f} min, tail after 50% done {100 * (d[-1] - d[len(d) // 2]) / d[-1]:3.0f}%")
