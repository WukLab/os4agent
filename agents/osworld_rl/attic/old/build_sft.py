"""Distill SUCCESSFUL pixel-agent rollouts into a11y-format SFT examples.   run on 02 in the osworld dir:
  venv/bin/python build_sft.py traces/grpo_mb2 sft_grpo_mb2.jsonl
Each kept step -> {"messages": [system, user(task, history, linearized tree)], "response": "Thought: ...\\nAction: {json}"}.
Steps that cannot be expressed as an element id (click on page content / canvas, drags) are skipped; the history only shows kept steps."""
import glob, gzip, json, os, re, sys
sys.path.insert(0, "OSWorld"); sys.path.insert(0, ".")
from mm_agents.a11y_owl_agent import SYSTEM, HISTORY, linearize
run, out = sys.argv[1], sys.argv[2]
instr = {os.path.basename(p)[:-5]: json.load(open(p))["instruction"] for p in glob.glob("OSWorld/evaluation_examples/examples/*/*.json")}
n = kept = skipped = ro = 0; per_task = {}
with open(out, "w") as f:
    for d in sorted(glob.glob(f"{run}/results/*/*/*/*/*__g*")):
        if not os.path.exists(f"{d}/result.txt") or float(open(f"{d}/result.txt").read()) < 1.0: continue
        task = os.path.basename(d).rsplit("__g", 1)[0]; ro += 1; hist = []
        for l in open(f"{d}/traj.jsonl"):
            t = json.loads(l)
            if "step_num" not in t: continue
            n += 1; code = t["action"]; h = t.get("a11y_hit"); act = None; thought = None
            tf = f"{d}/step_{t['step_num']}_{t['action_timestamp']}.a11y.xml.gz"
            if not os.path.exists(tf): skipped += 1; continue
            text, rows = linearize(gzip.open(tf, "rt").read())
            m = re.search(r"pyautogui\.(click|doubleClick|rightClick)\(", code)
            if code.strip() == "DONE": act, thought = {"action": "done"}, "The task is complete."
            elif m and h and h.get("key"):
                idx = [i for i, (r, nm, b) in enumerate(rows) if r == h["role"] and nm[:80] == h["name"][:80] and list(b) == h["bbox"]]
                if idx: act = {"action": {"click": "click", "doubleClick": "double_click", "rightClick": "right_click"}[m.group(1)], "id": idx[0]}; thought = f'Use the {rows[idx[0]][0]} "{rows[idx[0]][1]}".'
            elif "pyautogui.write(" in code:
                w = re.search(r"pyautogui\.write\('(.*)'", code)
                if w: act = {"action": "type", "text": w.group(1).replace("\\'", "'") + ("\n" if "press('enter')" in code else "")}; thought = "Type the needed text."
            elif "pyautogui.hotkey(" in code:
                k = re.search(r"pyautogui\.hotkey\((.*?)\)", code)
                if k: act = {"action": "key", "keys": re.findall(r"'([^']+)'", k.group(1))}; thought = "Use the keyboard shortcut."
            if act is None: skipped += 1; continue
            hs = "\n".join(f"{i + 1}. {x}" for i, x in enumerate(hist[-HISTORY:])) or "(none)"
            user = f"Task: {instr[task]}\n\nPrevious actions:\n{hs}\n\nAccessibility tree:\n{text}\n\nNext action?"
            f.write(json.dumps({"messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
                                "response": f"Thought: {thought}\nAction: {json.dumps(act)}", "task": task}) + "\n")
            hist.append(json.dumps(act) + (f'  [{rows[act["id"]][0]} "{rows[act["id"]][1]}"]' if "id" in act else "")); kept += 1; per_task[task] = per_task.get(task, 0) + 1
print(f"successful rollouts {ro}; steps {n}: kept {kept}, skipped {skipped} (not expressible as an element id); per task {per_task}")
