"""Why do state-matched pairs (same strict pre-screen, same elem action) sometimes have different post-screens?  python analyze_lazy3.py traces/<run>"""
import glob, os, re, sys, collections
R = sys.argv[1]; sys.argv = ["x", R, "1"]
exec(open("analyze_gui.py").read().split('print("\\n== causal')[0])
from PIL import Image
import numpy as np
dirs = {}
for d in glob.glob(f"{R}/results/*/*/*/*/*__g*"):
    m = re.match(r"(.*)__g(\d+)$", os.path.basename(d)); dirs[(m.group(1), int(m.group(2)))] = d
def img(t, g, s):
    f = f"{dirs[(t, g)]}/{s['screenshot_file']}"
    return np.asarray(Image.open(f).convert("L").resize((384, 216)), dtype=np.int16) if os.path.exists(f) else None
chg = lambda a, b: int((np.abs(a - b) > 25).sum())
xy = lambda s: [float(v) for v in re.findall(r"-?\d+\.\d+|-?\d+", exact(s))[:2]] if kind(s["action"]) in ("click", "doubleClick") else None
rows = []
for t, g in groups.items():
    steps = []
    for r, tr in g.items():
        post = [img(t, r, s) for s in tr]
        for i, s in enumerate(tr):
            if kind(s["action"]) in ("DONE", "FAIL"): continue
            steps.append(dict(r=r, i=i, s=s, pre=("INIT" if i == 0 else post[i - 1]), post=post[i], key=elem(s), kd=kind(s["action"])))
    for x in steps:
        for y in steps:
            if y["r"] >= x["r"] or y["key"] != x["key"]: continue
            pp = (isinstance(x["pre"], str) and isinstance(y["pre"], str)) or (not isinstance(x["pre"], str) and not isinstance(y["pre"], str) and chg(x["pre"], y["pre"]) <= 30)
            if not pp or x["post"] is None or y["post"] is None: continue
            a, b = xy(x["s"]), xy(y["s"]); dist = float(np.hypot(a[0] - b[0], a[1] - b[1])) if a and b else None
            rows.append((chg(x["post"], y["post"]), dist, x["kd"], x["i"]))
n = len(rows); print(f"{n} state-matched, same-element pairs (each pair = two REAL executions from the same screen)")
bins = [(0, 30), (31, 200), (201, 2000), (2001, 10**9)]
print("post-screen changed pixels:", {f"{lo}-{hi if hi<10**9 else 'inf'}": f"{sum(lo<=r[0]<=hi for r in rows)/n:.0%}" for lo, hi in bins})
cl = [r for r in rows if r[1] is not None]
for nm, f in (("clicks <=3px apart", lambda r: r[1] <= 3), ("clicks 3-15px apart", lambda r: 3 < r[1] <= 15), ("clicks >15px apart", lambda r: r[1] > 15)):
    sub = [r for r in cl if f(r)]
    if sub: print(f"  {nm:20s} n={len(sub):3d}  post equal (<=30px) {sum(r[0]<=30 for r in sub)/len(sub):4.0%}   >2000 px different {sum(r[0]>2000 for r in sub)/len(sub):4.0%}")
by = collections.defaultdict(list)
for r in rows: by[r[2]].append(r[0] <= 30)
print("by action kind (post equal):", {k: f"{sum(v)/len(v):.0%} (n={len(v)})" for k, v in by.items()})
