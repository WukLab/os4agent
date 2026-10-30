"""TAGE per epoch (all earlier epochs as warm data): top-1, top-2, the ceiling (true action anywhere in its top-8
candidates), and top-1 / top-2 within the predictable steps (those under the ceiling).
  venv/bin/python tage_ceiling.py EPOCH1_DIR EPOCH2_DIR ..."""
import os, sys
from collections import defaultdict
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "tage_epochs.py")).read().split("def score")[0]
exec(src)


def score8(warm, cur):
    t = OnlineTage(8)
    if warm:
        t.warm(warm)
    hist = defaultdict(list)
    n = h1 = h2 = h8 = 0
    for _, d, _, task, key in steps_of(cur):
        if key is None:
            continue
        g = t.tage.predict(task, hist[d])[0]
        n += 1
        h1 += bool(g) and g[0] == key
        h2 += key in g[:2]
        h8 += key in g[:8]
        t.tage.update(task, hist[d], key)
        hist[d].append(key)
    return n, h1 / n, h2 / n, h8 / n


print(f"{'epoch':6s} {'top-1':>6s} {'top-2':>6s} {'ceiling (top-8)':>16s} {'top-1 | predictable':>20s} {'top-2 | predictable':>20s}")
for e, cur in enumerate(epochs, 1):
    n, h1, h2, h8 = score8(epochs[:e - 1], cur)
    print(f"{e:<6d} {h1:6.1%} {h2:6.1%} {h8:16.1%} {h1 / h8:20.1%} {h2 / h8:20.1%}")
