"""Sibling-rollout predictor and fuzzy re-find, evaluated offline on a run (causal: only sibling steps already taken).
Sibling guess for rollout r at step i with last action L: what a sibling did right after L (most recent), else what a
sibling did at step i. Compared with TAGE on all eligible steps (i >= 2) and on TAGE's no-prediction steps."""
import json, glob, os, sys
from collections import Counter
sys.path.insert(0, "/mnt/ssd2/vikranth/osworld")
from toolspec.online import OnlineTage, web_step
from spec_exec import ActionBook
run, warm = sys.argv[1], sys.argv[2].split(",")
T, B = OnlineTage(topk=2), ActionBook()
T.warm([f"traces/{w}" for w in warm])
for w in warm:
    for d in glob.glob(f"traces/{w}/*/*__g*"):
        for s in (json.loads(l) for l in open(d + "/traj.jsonl") if l.strip()):
            try: B.remember(web_step(d, s)[1], json.loads(s["action"]), s.get("a11y_hit"))
            except Exception: pass
steps = []
for d in glob.glob(f"traces/{run}/*/*__g*"):
    chat = [json.loads(l) for l in open(d + "/chat.jsonl")]
    for i, s in enumerate(json.loads(l) for l in open(d + "/traj.jsonl") if l.strip()):
        if i < len(chat) and "action_timestamp" in s:
            steps.append((s["action_timestamp"], d, i, s, chat[i].get("rows") or []))
steps.sort()
def usable(g, rows, fuzzy):
    ent = B.acts.get(g)
    if ent is None or ent[0].get("action") == "drag": return False
    if not ent[1]: return True
    role, name = ent[1]["key"].split("|", 1)
    if any(f"{x[0]}|{x[1][:60]}" == ent[1]["key"] for x in rows): return True
    return fuzzy and any(x[0] == role and x[1].split(":")[0].strip()[:30] == name.split(":")[0].strip()[:30] for x in rows)
hist, sib, c = {}, {}, Counter()
for _, d, i, s, rows in steps:
    task = os.path.basename(d).split("__g")[0]
    h = hist.setdefault(d, []); _, key = web_step(d, s)
    if i >= 2 and key is not None:
        tg = (T.tage.predict(task, h)[0] or [None])[0]
        others = [x for x in sib.get(task, []) if x[0] != d]
        after = [x[3] for x in others if h and x[2] == h[-1]]
        same_i = [x[3] for x in others if x[1] == i]
        sg = (after[-1] if after else same_i[-1] if same_i else None)
        combo = tg or sg  # TAGE, sibling when TAGE has nothing
        for name, g in (("TAGE", tg), ("sibling", sg), ("TAGE else sibling", combo)):
            c[f"{name}: has guess"] += g is not None
            c[f"{name}: usable"] += g is not None and usable(g, rows, False)
            c[f"{name}: usable+fuzzy"] += g is not None and usable(g, rows, True)
            c[f"{name}: correct+usable(fuzzy)"] += g == key and usable(g, rows, True)
        if tg is None:
            c["(TAGE none) sibling correct"] += sg == key
            c["(TAGE none) steps"] += 1
        c["steps"] += 1
    if key is not None:
        T.tage.update(task, h, key); h.append(key)
        try: B.remember(key, json.loads(s["action"]), s.get("a11y_hit"))
        except Exception: pass
        sib.setdefault(task, []).append((d, i, h[-2] if len(h) > 1 else None, key))
n = c["steps"]
for k in sorted(c):
    if k != "steps": print(f"  {k:34} {c[k]:4d} ({100*c[k]/n:4.1f}% of {n} steps)" if not k.startswith("(") else f"  {k:34} {c[k]:4d}")
