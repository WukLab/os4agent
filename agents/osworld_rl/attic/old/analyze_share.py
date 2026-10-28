"""State-sharing estimate (needs CoW VM fork).   python analyze_share.py traces/<run>
If an EARLIER sibling issued the same action history through step i (inclusive), its post-step-i VM state is (approximately) ours,
so instead of executing step i we fork the sibling's VM. We still call the LLM (our action is sampled independently).
Saved time = clip(t_our_action - t_sibling_action, 0, V): the sibling's VM-side work must have finished by the time we would have needed it.
Also checks the 'same state' claim by comparing post-step screenshots (8x? downsampled gray diff)."""
import glob, os, re, sys, collections
R = sys.argv[1]; sys.argv = ["x", R, "1"]
exec(open("analyze_gui.py").read().split('print("\\n== causal')[0])
from PIL import Image
import numpy as np
dirs = {}
for d in glob.glob(f"{R}/results/*/*/*/*/*__g*"):
    m = re.match(r"(.*)__g(\d+)$", os.path.basename(d)); dirs[(m.group(1), int(m.group(2)))] = d
_img = {}
def small(t, g, s):
    k = (t, g, s["step_num"])
    if k not in _img:
        f = f"{dirs[(t, g)]}/{s['screenshot_file']}"
        _img[k] = np.asarray(Image.open(f).convert("L").resize((96, 54)), dtype=np.float32) if os.path.exists(f) else None
    return _img[k]
n = elig = 0; saved = 0.0; diffs = []; by_i = collections.defaultdict(lambda: [0, 0])
for t, g in groups.items():
    for r, tr in g.items():
        for i, s in enumerate(tr):
            if kind(s["action"]) in ("DONE", "FAIL"): continue
            n += 1; b = "0" if i == 0 else "1-2" if i < 3 else "3-5" if i < 6 else "6+"; by_i[b][1] += 1
            mine = [elem(x) for x in tr[:i + 1]]; best = None
            for q, o in g.items():
                if q == r or len(o) <= i or o[i]["t"] >= s["t"]: continue
                if [elem(x) for x in o[:i + 1]] == mine and (best is None or o[i]["t"] < best[0]): best = (o[i]["t"], q)
            if not best: continue
            elig += 1; by_i[b][0] += 1; saved += min(max(s["t"] - best[0], 0), V)
            a, c = small(t, r, s), small(t, best[1], g[best[1]][i])
            if a is not None and c is not None: diffs.append(float(np.abs(a - c).mean()))
print(f"executable steps {n}; adoptable from an earlier same-history sibling: {elig} ({elig/n:.1%})")
print("  by step index:", {k: f"{v[0]/v[1]:.0%} (n={v[1]})" for k, v in sorted(by_i.items())})
print(f"VM-side time saved {saved/(n*V):.1%}, step time saved {saved/(n*(V+llm_p50)):.1%}  (no wasted execution; fork cost not charged)")
if diffs:
    d = sorted(diffs); print(f"post-step screenshot mean-abs-diff (0-255 gray, 96x54): p50 {d[len(d)//2]:.2f} p90 {d[int(len(d)*.9)]:.2f}; <=2.0: {sum(x<=2 for x in d)/len(d):.0%}, <=5.0: {sum(x<=5 for x in d)/len(d):.0%}  (n={len(d)})")
# reference: diff between a rollout and a DIFFERENT-history sibling at the same step
ref = []
for t, g in groups.items():
    for r, tr in g.items():
        for i, s in enumerate(tr[:6]):
            for q, o in g.items():
                if q != r and len(o) > i and [elem(x) for x in o[:i + 1]] != [elem(x) for x in tr[:i + 1]]:
                    a, c = small(t, r, s), small(t, q, o[i])
                    if a is not None and c is not None: ref.append(float(np.abs(a - c).mean())); break
if ref: d = sorted(ref); print(f"reference, different-history siblings: p50 {d[len(d)//2]:.2f} p90 {d[int(len(d)*.9)]:.2f}  (n={len(d)})")
