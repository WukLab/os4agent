"""Baseline vs stop-at-done prompt on the same tasks: per task the steps and outcome; overall solved, rollouts ending
before the cap split into correct done / premature done (done but reward 0) / other, and the tail after 50% done."""
import json, sys, glob, statistics as st
CAP = 15
diff = {l.split("\t")[1]: l.split("\t")[2] for l in open("scout_candidates.tsv") if "\t" in l}

def load(run):
    out = {}
    for e in map(json.loads, open(f"traces/{run}/events.jsonl")):
        if e["event"] == "rollout_done":
            last = [json.loads(l) for l in glob.glob(f"traces/{run}/*/{e['task']}__g{e['k']}/traj.jsonl") and
                    open(glob.glob(f"traces/{run}/*/{e['task']}__g{e['k']}/traj.jsonl")[0]) if l.strip()]
            said_done = bool(last) and '"done"' in last[-1].get("action", "")
            out.setdefault(e["task"], []).append((e["steps"], e["reward"] >= 0.9, said_done, e["secs"]))
    return out

runs = sys.argv[1:]
data = [load(r) for r in runs]
print(f"{'task':9} {'diff':6} " + " | ".join(f"{r:>22}" for r in runs))
for t in sorted(data[0], key=lambda t: ["easy", "medium", "hard"].index(diff.get(t, "hard"))):
    cells = []
    for d in data:
        rs = d.get(t, [])
        cells.append(f"{str([s for s, *_ in rs]):>14} ok {sum(o for _, o, *_ in rs)}/{len(rs)}")
    print(f"{t[:8]:9} {diff.get(t, '?'):6} " + " | ".join(f"{c:>22}" for c in cells))
for r, d in zip(runs, data):
    R = [x for rs in d.values() for x in rs]
    early = [x for x in R if x[0] < CAP]
    secs = sorted(x[3] for x in R)
    print(f"{r}: {len(R)} rollouts, solved {sum(x[1] for x in R)}, median steps {st.median(x[0] for x in R)}, "
          f"before cap {len(early)} ({100 * len(early) / len(R):.0f}%): correct done {sum(x[1] and x[2] for x in early)}, "
          f"premature done {sum(x[2] and not x[1] for x in early)}, other {sum(not x[2] for x in early)}; "
          f"solved but ran to cap {sum(x[1] and x[0] >= CAP for x in R)}; tail after 50% done {100 * (secs[-1] - secs[len(secs) // 2]) / secs[-1]:.0f}%")
