"""Instruction + each step's action, target and stated reason, for rollout g<k> of every task in a run."""
import json, glob, os, sys
run, k = sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "0"
for d in sorted(glob.glob(f"traces/{run}/*/*__g{k}")):
    app, tid = d.split("/")[2], os.path.basename(d).split("__g")[0]
    t = json.load(open(f"OSWorld/evaluation_examples/examples/{app}/{tid}.json"))
    print(f"== {app} {tid[:8]}: {t['instruction'][:160]}")
    for i, l in enumerate(open(f"{d}/chat.jsonl")):
        x = json.loads(l)
        a, j = x["action"], x["action"].get("id")
        tgt = f"{x['rows'][j][0]} \"{x['rows'][j][1][:38]}\"" if isinstance(j, int) and 0 <= j < len(x["rows"]) else ""
        why = x["response"].rsplit("</think>", 1)[-1].replace("\n", " ").strip()
        act = json.dumps({kk: v for kk, v in a.items() if kk != "error"})
        print(f"   {i + 1:2}. {act[:62]:62} -> {tgt:44} | {why[:100]}")
    r = open(f"{d}/result.txt").read().strip() if os.path.exists(f"{d}/result.txt") else "running"
    print(f"   result: {r}")
