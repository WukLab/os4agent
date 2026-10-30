"""Per group: which cache entry each rollout restores (its deepest matching prefix, unlimited depth, cache = the previous
epoch's paths), how deep it is, and how many rollouts share it (= copies forked from one template).
  cd osworld; python3 share_sim.py grpo_tfork16_pfx 5"""
import collections, glob, json, os, statistics as st, sys

sys.path.insert(0, os.getcwd())
from toolspec.keys import action_key

exp, n_ep = sys.argv[1], int(sys.argv[2])


def paths(e):
    for f in sorted(glob.glob(f"traces/{exp}_e{e}/*/*__g*/traj.jsonl")):
        task = os.path.basename(os.path.dirname(f)).split("__")[0]
        yield task, tuple(action_key(json.loads(json.loads(l)["action"]), json.loads(l).get("a11y_hit")) for l in open(f))


for e in range(1, n_ep):
    nodes = {(t, p[:i + 1]) for t, p in paths(e - 1) for i in range(len(p))}
    entries = collections.Counter()  # (task, prefix) restored -> rollouts restoring it
    no_hit = 0
    for t, p in paths(e):
        n = 0
        while n < len(p) and (t, p[:n + 1]) in nodes:
            n += 1
        if n:
            entries[(t, p[:n])] += 1
        else:
            no_hit += 1
    sizes = list(entries.values())
    depth = [len(k[1]) for k, c in entries.items() for _ in range(c)]
    hist = collections.Counter(sizes)
    print(f"epoch {e}: {sum(sizes)} rollouts restore {len(entries)} distinct entries ({no_hit} no hit); "
          f"rollouts per entry: " + ", ".join(f"{s}x{hist[s]}" for s in sorted(hist)) +
          f"; restore depth per rollout: median {st.median(depth)}, mean {st.mean(depth):.1f}, "
          f"share at depth >= 4: {sum(d >= 4 for d in depth) / len(depth):.0%}")
