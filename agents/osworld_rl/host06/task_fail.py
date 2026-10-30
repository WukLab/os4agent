"""Per task: solved, invalid actions, rollouts that hit the step cap, median output tokens. python3 task_fail.py NAME=TRACE ..."""
import glob, json, os, statistics as st, sys
runs = [a.split("=", 1) for a in sys.argv[1:]]
rows = {}
for name, d in runs:
    for r in glob.glob(f"{d}/*/*__g*"):
        t = os.path.basename(r)[:8]
        try:
            tr = [json.loads(l) for l in open(f"{r}/traj.jsonl")]
            ch = [json.loads(l) for l in open(f"{r}/chat.jsonl")]
            rew = float(open(f"{r}/result.txt").read())
        except (OSError, ValueError):
            continue
        x = rows.setdefault(t, {}).setdefault(name, {"solved": 0, "invalid": 0, "cap": 0, "tok": [], "done_fail": 0})
        acts = [json.loads(s["action"]) for s in tr]
        x["solved"] += rew > 0
        x["invalid"] += sum(a.get("action") == "invalid" for a in acts)
        x["cap"] += len(tr) >= 20
        x["done_fail"] += bool(acts) and acts[-1].get("action") == "done" and rew == 0
        x["tok"] += [c["completion_tokens"] for c in ch if c.get("completion_tokens")]
names = [n for n, _ in runs]
print("task     | " + " | ".join(f"{n}: solved/invalid/cap/said-done-but-wrong/med-tokens" for n in names))
for t in sorted(rows):
    cells = []
    for n in names:
        x = rows[t].get(n)
        cells.append(f"{x['solved']}/{x['invalid']}/{x['cap']}/{x['done_fail']}/{st.median(x['tok']) if x['tok'] else 0:.0f}" if x else "-")
    if any(rows[t].get(n, {}).get("solved") for n in names):
        print(f"{t} | " + " | ".join(cells))
