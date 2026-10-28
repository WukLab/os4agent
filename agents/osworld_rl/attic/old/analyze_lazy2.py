"""Validate state-based adoption with a STRICT screen comparison (384x216 gray; 'changed pixels' = |diff|>25).  python analyze_lazy2.py traces/<run> [maxpx=30]
Match B = earlier sibling step, same pre-screen (strict), same action (elem).  A B-match is VALID iff the two POST screens are also strictly equal
(if the pre-states were really equal and the action is equivalent, the results must agree)."""
import glob, os, re, sys
R = sys.argv[1]; MAXPX = int(sys.argv[2]) if len(sys.argv) > 2 else 30; sys.argv = ["x", R, "1"]
exec(open("analyze_gui.py").read().split('print("\\n== causal')[0])
from PIL import Image
import numpy as np
dirs = {}
for d in glob.glob(f"{R}/results/*/*/*/*/*__g*"):
    m = re.match(r"(.*)__g(\d+)$", os.path.basename(d)); dirs[(m.group(1), int(m.group(2)))] = d
def img(t, g, s):
    f = f"{dirs[(t, g)]}/{s['screenshot_file']}"
    return np.asarray(Image.open(f).convert("L").resize((384, 216)), dtype=np.int16) if os.path.exists(f) else None
import gzip, xml.etree.ElementTree as ET
sys.path.insert(0, "."); from a11y_hit import _box, INTERACTIVE
def tree(t, g, s):
    f = f"{dirs[(t, g)]}/step_{s['step_num']}_{s['action_timestamp']}.a11y.xml.gz"
    if not os.path.exists(f): return None
    try: return frozenset(f"{e.tag}|{e.get('name', '')}|{_box(e)}" for e in ET.fromstring(gzip.open(f, "rt").read()).iter() if e.tag in INTERACTIVE and _box(e))
    except Exception: return None
JAC = float(os.environ.get("JAC", "0"))
def jac(a, b): return a is not None and b is not None and len(a | b) > 0 and len(a & b) / len(a | b) >= JAC
def close(a, b): return a is not None and b is not None and int((np.abs(a - b) > 25).sum()) <= MAXPX
n = nB = nBv = 0; svB = svBv = 0.0
for t, g in groups.items():
    steps = []
    for r, tr in g.items():
        post = [img(t, r, s) for s in tr]
        for i, s in enumerate(tr):
            if kind(s["action"]) in ("DONE", "FAIL"): continue
            steps.append(dict(tr=tree(t, r, s), r=r, i=i, s=s, pre=("INIT" if i == 0 else post[i - 1]), post=post[i], key=elem(s)))
    same = lambda p, q: (isinstance(p, str) and isinstance(q, str)) or (not isinstance(p, str) and not isinstance(q, str) and close(p, q))
    for x in steps:
        n += 1; sv = lambda y: min(max(x["s"]["t"] - y["s"]["t"], 0), V)
        b = [y for y in steps if y["r"] != x["r"] and y["s"]["t"] < x["s"]["t"] and y["key"] == x["key"] and same(y["pre"], x["pre"]) and (JAC == 0 or jac(y["tr"], x["tr"]))]
        if b: nB += 1; svB += max(sv(y) for y in b)
        bv = [y for y in b if close(y["post"], x["post"])]
        if bv: nBv += 1; svBv += max(sv(y) for y in bv)
den = n * (V + llm_p50)
print(f"strict screen match (<= {MAXPX} changed px of 82944): {n} steps")
print(f"  B matches {nB/n:5.1%} (step time {svB/den:5.1%}); of these VALID (post-screens also equal): {nBv/max(nB,1):5.1%} of matches -> verified coverage {nBv/n:5.1%}, verified step time {svBv/den:5.1%}")
