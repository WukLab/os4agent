"""(a) probe-and-stop for zero-variance GRPO groups   (b) abort rollouts stuck in no-op loops.   python analyze_alloc.py traces/<run>"""
import glob, itertools, os, re, sys
R = sys.argv[1]; sys.argv = ["x", R, "1"]
exec(open("analyze_gui.py").read().split('print("\\n== causal')[0])
from PIL import Image
import numpy as np
dirs = {}
for d in glob.glob(f"{R}/results/*/*/*/*/*__g*"):
    m = re.match(r"(.*)__g(\d+)$", os.path.basename(d)); dirs[(m.group(1), int(m.group(2)))] = d
rew = {k: float(open(f"{d}/result.txt").read()) for k, d in dirs.items() if os.path.exists(f"{d}/result.txt")}
G = {}
for (t, g), r in rew.items(): G.setdefault(t, {})[g] = r
print("== (a) probe m rollouts; if all equal reward, skip the rest of the group")
tot = sum(len(v) for v in G.values()); zero = sum(len(set(v.values())) == 1 for v in G.values())
print(f"   groups with zero variance: {zero}/{len(G)} -> {sum(len(v) for v in G.values() if len(set(v.values()))==1)/tot:.0%} of rollouts carry no GRPO signal")
for m in (2, 3, 4):
    saved = lost = mixed = 0; n = 0
    for t, v in G.items():
        gs = sorted(v); subs = list(itertools.combinations(gs, m)); ismixed = len(set(v.values())) > 1; mixed += ismixed
        stop = sum(len({v[g] for g in s}) == 1 for s in subs) / len(subs)          # P(probe all equal)
        saved += stop * (len(gs) - m); n += len(gs); lost += stop if ismixed else 0
    print(f"   m={m}: rollouts saved {saved/n:5.1%}; mixed groups wrongly stopped {lost/max(mixed,1):4.0%} (n_mixed={mixed})")
print("== (b) abort after k consecutive steps whose screen did not change (<=30 px of 82944 at 384x216)")
img = lambda t, g, s: np.asarray(Image.open(f"{dirs[(t, g)]}/{s['screenshot_file']}").convert("L").resize((384, 216)), dtype=np.int16)
rows = []
for t, g in groups.items():
    for r, tr in g.items():
        if (t, r) not in rew: continue
        post = [img(t, r, s) for s in tr]; noop = [i > 0 and int((np.abs(post[i] - post[i - 1]) > 25).sum()) <= 30 for i in range(len(tr))]
        rows.append((rew[(t, r)], noop, len(tr)))
steps = sum(x[2] for x in rows); print(f"   no-op steps overall: {sum(sum(x[1]) for x in rows)/steps:.1%} of {steps}")
for k in (2, 3):
    sv = ab = fail_ab = succ_ab = 0
    for rw, noop, n in rows:
        run = 0; cut = None
        for i, z in enumerate(noop):
            run = run + 1 if z else 0
            if run >= k: cut = i; break
        if cut is not None: sv += n - 1 - cut; ab += 1; fail_ab += rw == 0; succ_ab += rw > 0
    print(f"   k={k}: rollouts aborted {ab}/{len(rows)} (of which reward 0: {fail_ab}, reward>0: {succ_ab}); steps saved {sv/steps:.1%}")
