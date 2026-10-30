"""The slowest rollout's actions: where else (epoch 1, epoch-2 siblings, its own earlier steps) each key appears."""
import glob, json, os, sys
sys.path[:0] = ["/mnt/ssd2/vikranth/osworld"]
from toolspec.keys import action_key
T = "/mnt/ssd2/vikranth/osworld/traces"
task, k = "7a4e4bc8", 4
keys = lambda f: [action_key(json.loads(s["action"]), s.get("a11y_hit")) for s in map(json.loads, open(f))]
me = keys(glob.glob(f"{T}/r128e2_SC2/*/{task}*__g{k}/traj.jsonl")[0])
tr = [json.loads(l) for l in open(glob.glob(f"{T}/r128e2_SC2/*/{task}*__g{k}/traj.jsonl")[0])]
e1 = [keys(f) for f in glob.glob(f"{T}/rec128_shot/*/{task}*/traj.jsonl")]
sib = [keys(f) for f in glob.glob(f"{T}/rec128e2_shot/*/{task}*/traj.jsonl") if not f.endswith(f"__g{k}/traj.jsonl")]
for i, key in enumerate(me):
    kind = tr[i].get("skipped") or "miss"
    print(f"{i + 1:2d} {kind:6s} {tr[i]['exec_s']:5.1f}s  {str(key)[:70]:70s} | epoch1 rollouts: {sum(key in r for r in e1)}/8, "
          f"siblings: {sum(key in r for r in sib)}/7, own earlier: {key in me[:i]}")
