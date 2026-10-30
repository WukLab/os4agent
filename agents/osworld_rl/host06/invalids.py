"""Every invalid action in a run: task, step, error, the end of the model's answer, tree size, and for id errors which
element the model named (ids past the end of the tree = element not in the tree)."""
import json, glob, re, sys
for f in sorted(glob.glob(f"traces/{sys.argv[1]}/*/*/chat.jsonl")):
    for i, l in enumerate(open(f)):
        x = json.loads(l)
        if x["action"].get("action") != "invalid":
            continue
        ans = x["response"].rsplit("</think>", 1)[-1].strip().replace("\n", " ")
        ids = re.findall(r'"(?:id|from|to)":\s*\[?"?(\d+)', ans.rsplit("Action:", 1)[-1])
        print(f"{f.split('/')[2]:20} {f.split('/')[3][:8]} g{f.split('__g')[1][0]} step {i + 1}: {x['action'].get('error', '')[:60]} | rows {len(x['rows'])} ids {ids}")
        print(f"     ...{ans[-260:]}")
