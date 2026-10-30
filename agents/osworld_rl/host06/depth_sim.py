"""How many steps would a prefix cache skip at a given depth? Replays the recorded trajectories of an RL run's epochs
through a simulated cache: a rollout's leading steps hit while (task, actions so far) is a path some earlier epoch
recorded. Counts are a lower bound (same-epoch sharing between rollouts is ignored).
  cd osworld; python3 depth_sim.py grpo_tfork16_pfx 5"""
import glob, json, os, sys

sys.path.insert(0, os.getcwd())
from toolspec.keys import action_key

exp, n_ep = sys.argv[1], int(sys.argv[2])


def rollouts(e):
    for f in sorted(glob.glob(f"traces/{exp}_e{e}/*/*__g*/traj.jsonl")):
        task = os.path.basename(os.path.dirname(f)).split("__")[0]
        steps = [json.loads(l) for l in open(f)]
        yield task, [action_key(json.loads(s["action"]), s.get("a11y_hit")) for s in steps], [s["exec_s"] for s in steps]


seen = set()  # (task, prefix tuple) recorded by earlier epochs
for e in range(n_ep):
    R = list(rollouts(e))
    if e:
        tot = sum(len(k) for _, k, _ in R)
        for depth in (3, 6, 10, 15):
            hit_steps, saved, restored = 0, 0.0, 0
            for task, keys, ex in R:
                n = 0
                while n < min(len(keys), depth) and (task, tuple(keys[:n + 1])) in seen:
                    n += 1
                hit_steps += n
                restored += n > 0
                saved += sum(ex[:n])  # recorded desktop time of those steps (0 for steps that were cache hits then)
            print(f"epoch {e} depth {depth:>2}: {hit_steps:>4}/{tot} steps hit ({hit_steps / tot:.0%}), "
                  f"{restored} rollouts restored, {hit_steps / max(restored, 1):.1f} steps per restore")
        print()
    mode = os.environ.get("MODE", "first")  # first: only epoch 0 saves; all: every epoch adds; prev: keep the last epoch only
    if mode == "prev":
        seen = set()
    if e == 0 or mode in ("all", "prev"):
        for task, keys, _ in R:
            for i in range(len(keys)):
                seen.add((task, tuple(keys[:i + 1])))
