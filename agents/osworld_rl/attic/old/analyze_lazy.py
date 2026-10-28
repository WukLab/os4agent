"""Lazy matching: identify interchangeable steps by SCREEN STATE instead of action history, and (upper bound) by RESULT.
  python analyze_lazy.py traces/<run> [tau=1.0]
 A history : earlier sibling, identical action history + same action          (previous design)
 B state   : earlier sibling step whose PRE-action screen is ~identical + same action (elem-level)     [verifiable before adopting]
 C result  : earlier sibling step from the same pre-state whose POST screen is ~identical, ANY action   [only verifiable after running ours]"""
import glob, os, re, sys
R = sys.argv[1]; TAU = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0; sys.argv = ["x", R, "1"]
exec(open("analyze_gui.py").read().split('print("\\n== causal')[0])
from PIL import Image
import numpy as np
dirs = {}
for d in glob.glob(f"{R}/results/*/*/*/*/*__g*"):
    m = re.match(r"(.*)__g(\d+)$", os.path.basename(d)); dirs[(m.group(1), int(m.group(2)))] = d
def img(t, g, s):
    f = f"{dirs[(t, g)]}/{s['screenshot_file']}"
    return np.asarray(Image.open(f).convert("L").resize((96, 54)), dtype=np.float32) if os.path.exists(f) else None
close = lambda a, b: a is not None and b is not None and float(np.abs(a - b).mean()) <= TAU
n = 0; A = B = C = BC = 0; svA = svB = svC = 0.0; classes = {}
for t, g in groups.items():
    steps = []
    for r, tr in g.items():
        post = [img(t, r, s) for s in tr]
        for i, s in enumerate(tr):
            if kind(s["action"]) in ("DONE", "FAIL"): continue
            steps.append(dict(r=r, i=i, s=s, pre=("INIT" if i == 0 else post[i - 1]), post=post[i], key=elem(s), hist=tuple(elem(x) for x in tr[:i + 1])))
    same = lambda p, q: (isinstance(p, str) and isinstance(q, str)) or (not isinstance(p, str) and not isinstance(q, str) and close(p, q))
    for x in steps:
        n += 1; e = [y for y in steps if y["r"] != x["r"] and y["s"]["t"] < x["s"]["t"]]
        sv = lambda y: min(max(x["s"]["t"] - y["s"]["t"], 0), V)
        a = [y for y in e if y["hist"] == x["hist"]]; b = [y for y in e if same(y["pre"], x["pre"]) and y["key"] == x["key"]]
        c = [y for y in e if same(y["pre"], x["pre"]) and (y["key"] == x["key"] or close(y["post"], x["post"]))]
        if a: A += 1; svA += max(sv(y) for y in a)
        if b: B += 1; svB += max(sv(y) for y in b)
        if c: C += 1; svC += max(sv(y) for y in c)
        if c and not b:
            ys = [y for y in c if y["key"] != x["key"]]; BC += 1
            if ys: classes[(kind(x["s"]["action"]), kind(ys[0]["s"]["action"]))] = classes.get((kind(x["s"]["action"]), kind(ys[0]["s"]["action"])), 0) + 1
den = n * (V + llm_p50)
print(f"tau={TAU}  {n} executable steps; V={V:.1f}s")
for nm, k, sv_ in (("A history-identical + same action", A, svA), ("B same pre-screen + same action", B, svB), ("C same pre-screen + same RESULT (any action)", C, svC)):
    print(f"  {nm:48s} coverage {k/n:5.1%}   step time adoptable {sv_/den:5.1%}")
print(f"  C-only steps (different action, same result): {BC}/{n} = {BC/n:.1%}; action-type pairs (ours, sibling's):", dict(sorted(classes.items(), key=lambda kv: -kv[1])[:5]))
