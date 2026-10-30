"""Per update: training stats; per epoch: agent behaviour. python3 why_drop.py"""
import glob, json, statistics as st
B = "pod_backup/grpo_think_reg/adapters"
print("update      groups_used samples  per-minibatch clip_frac            mean_ratio(min)  grad_norm(max)")
for a in ["e3_shot", "e4_shot", "e5_shot", "e6_shot"]:
    s = json.load(open(f"{B}/{a}/train_stats.json"))
    mb = s["stats"]
    print(f"{a:10s}  {s['used']:>4}/{s['groups']:<6} {s['samples']:>5}   {[round(m['clip_frac'], 3) for m in mb]}  "
          f"{min(m['mean_ratio'] for m in mb):.3f}          {max(m['grad_norm'] for m in mb):.3f}")
print()
print("epoch  solved  median_steps  hit_cap(20)  invalid_actions  repeated_same_action  median_out_tokens  done_without_success")
for e, d in [("e1", "rec128_shot"), ("e2", "rec128e2_shot"), ("e3", "rec128e3_shot"), ("e4", "rec128e4_shot"), ("e5", "rec128e5_shot")]:
    steps, cap, inval, rep, toks, solved, done_fail = [], 0, 0, 0, [], 0, 0
    for r in glob.glob(f"traces/{d}/*/*__g*"):
        try:
            tr = [json.loads(l) for l in open(f"{r}/traj.jsonl")]
            ch = [json.loads(l) for l in open(f"{r}/chat.jsonl")]
            rew = float(open(f"{r}/result.txt").read())
        except (OSError, ValueError):
            continue
        acts = [json.loads(t["action"]) for t in tr]
        steps.append(len(tr)); cap += len(tr) >= 20; solved += rew > 0
        inval += sum(a.get("action") == "invalid" for a in acts)
        rep += sum(1 for x, y in zip(tr, tr[1:]) if x["action"] == y["action"])
        toks += [c.get("completion_tokens") for c in ch if c.get("completion_tokens")]
        done_fail += (acts and acts[-1].get("action") == "done" and rew == 0)
    print(f"{e:5s}  {solved:>6}  {st.median(steps):>12}  {cap:>11}  {inval:>15}  {rep:>20}  {st.median(toks) if toks else 0:>17}  {done_fail:>20}")
