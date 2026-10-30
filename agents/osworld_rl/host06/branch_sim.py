"""Snapshots only at divergence points + replay from the nearest snapshot ancestor, vs a snapshot at every prefix.
Trie of epoch e-1's paths (per task); later rollouts hit along it (unlimited depth). On the first miss at depth n the
desktop must be at node n: restore the deepest snapshotted ancestor m <= n and replay actions m+1..n.
  cd osworld; python3 branch_sim.py grpo_tfork16_pfx 5"""
import collections, glob, json, os, statistics as st, sys

sys.path.insert(0, os.getcwd())
from toolspec.keys import action_key

exp, n_ep = sys.argv[1], int(sys.argv[2])


def paths(e):
    for f in sorted(glob.glob(f"traces/{exp}_e{e}/*/*__g*/traj.jsonl")):
        task = os.path.basename(os.path.dirname(f)).split("__")[0]
        yield task, tuple(action_key(json.loads(json.loads(l)["action"]), json.loads(l).get("a11y_hit")) for l in open(f))


for e in range(1, n_ep):
    children = collections.defaultdict(set)  # node -> distinct next actions
    nodes = set()
    for task, p in paths(e - 1):
        for i in range(len(p)):
            nodes.add((task, p[:i + 1]))
            if i + 1 < len(p):
                children[(task, p[:i + 1])].add(p[i + 1])
    # snapshot sets: every node / divergence points (>= 2 children) plus each task's first-step nodes
    branch = {n for n in nodes if len(children[n]) >= 2 or len(n[1]) == 1}
    for name, snaps in (("every prefix", nodes), ("divergence points only", branch)):
        replays, restores, hits = [], 0, 0
        for task, p in paths(e):
            n = 0
            while n < len(p) and (task, p[:n + 1]) in nodes:
                n += 1
            hits += n
            if n:
                restores += 1
                m = max(k for k in range(1, n + 1) if (task, p[:k]) in snaps)
                replays.append(n - m)
        print(f"epoch {e} {name:<23} snapshots {len(snaps):>5}  hit steps {hits:>4}  restores {restores:>3}  "
              f"replay steps per restore: mean {st.mean(replays):.2f}, max {max(replays)}, "
              f"share needing replay {sum(r > 0 for r in replays) / len(replays):.0%}")
    print()
