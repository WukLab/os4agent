"""Why pre-fork had no usable guess: replay TAGE + ActionBook (warmed like --spec-warm) over a run's steps in time order;
for each step n+1 classify the top guess: no prediction / action never seen by the book / drag / target element not in
the tree (and whether a same-role element with the same stable name prefix exists) / usable (and correct?)."""
import json, glob, os, sys
from collections import Counter
sys.path.insert(0, "/mnt/ssd2/vikranth/osworld")
from toolspec.online import OnlineTage, web_step
from spec_exec import ActionBook
run, warm = sys.argv[1], sys.argv[2].split(",")
T, B = OnlineTage(topk=2), ActionBook()
T.warm([f"traces/{w}" for w in warm])
def remember_dir(d):
    for s in (json.loads(l) for l in open(d + "/traj.jsonl") if l.strip()):
        if "action" not in s: continue
        try: act = json.loads(s["action"])
        except Exception: continue
        _, key = web_step(d, s)
        B.remember(key, act, s.get("a11y_hit"))
for w in warm:
    for d in glob.glob(f"traces/{w}/*/*__g*"): remember_dir(d)
steps = []
for d in glob.glob(f"traces/{run}/*/*__g*"):
    chat = [json.loads(l) for l in open(d + "/chat.jsonl")]
    traj = [json.loads(l) for l in open(d + "/traj.jsonl") if l.strip()]
    for i, s in enumerate(traj):
        if i < len(chat) and "action_timestamp" in s:
            steps.append((s["action_timestamp"], d, i, s, chat[i].get("rows") or []))
steps.sort()
hist, why, examples = {}, Counter(), {}
for _, d, i, s, rows in steps:
    task = os.path.basename(d).split("__g")[0]
    h = hist.setdefault(d, [])
    _, key = web_step(d, s)
    if i >= 2:  # pre-fork speculates from step 3 (index 2); the copy sees this step's tree
        g = T.tage.predict(task, h)[0]
        if not g: r = "no prediction"
        else:
            g0 = g[0]
            ent = B.acts.get(g0)
            if ent is None: r = "book: action never seen"
            elif ent[0].get("action") == "drag": r = "drag (two targets)"
            elif ent[1] and not any(f"{x[0]}|{x[1][:60]}" == ent[1]["key"] for x in rows):
                role, name = ent[1]["key"].split("|", 1)
                stable = name.split(":")[0].strip()
                near = any(x[0] == role and x[1].split(":")[0].strip() == stable for x in rows)
                r = "element missing, same address/prefix present" if near else "element missing from tree"
                examples.setdefault(r, []).append(ent[1]["key"][:50])
            else: r = "usable: " + ("correct" if g0 == key else "wrong")
        why[r] += 1
    if key is not None:
        T.tage.update(task, h, key); h.append(key)
        try: B.remember(key, json.loads(s["action"]), s.get("a11y_hit"))
        except Exception: pass
n = sum(why.values())
for r, c in why.most_common(): print(f"  {c:4d} ({100*c/n:4.1f}%) {r}")
for r, ex in examples.items(): print(f"  e.g. [{r}]: {ex[:6]}")
