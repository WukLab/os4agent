"""Hit rate per GRPO epoch: knowledge = all earlier epochs vs only the last epoch, for the prefix (screen) cache and
TAGE speculation (top-1). Epoch 1 has no earlier epoch (cold) in both.

  venv/bin/python hitrate_window_plot.py OUT_DIR EPOCH1_DIR EPOCH2_DIR ...

Writes hitrate_window.png/.svg and hitrate_window.csv. Same scoring as hitrate_plot.py.
"""
import csv, os, sys

out, epochs = sys.argv[1], sys.argv[2:]
here = os.path.dirname(os.path.abspath(__file__))


def load(name):
    src = open(os.path.join(here, name)).read().split("\nprint(")[0]
    ns = {"__file__": os.path.join(here, name)}
    argv, sys.argv = sys.argv, [name, *epochs]
    try:
        exec(src, ns)
    finally:
        sys.argv = argv
    return ns["score"]


cache_score, tage_score = load("cache_epochs.py"), load("tage_epochs.py")
rows = []
for e, cur in enumerate(epochs, 1):
    allw, last = epochs[:e - 1], epochs[e - 2:e - 1] if e > 1 else []
    r = dict(epoch=e, trace=os.path.basename(cur),
             cache_all=cache_score(allw, cur)[2], cache_last=cache_score(last, cur)[2],
             spec1_all=tage_score(allw, cur)[1], spec1_last=tage_score(last, cur)[1])
    rows.append(r)
    print(f"epoch {e}: cache all {r['cache_all']:.1%} last {r['cache_last']:.1%} | spec top-1 all {r['spec1_all']:.1%} "
          f"last {r['spec1_last']:.1%}")

os.makedirs(out, exist_ok=True)
with open(os.path.join(out, "hitrate_window.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK, MUTED, GRID = "#1f1f1f", "#6b6b6b", "#e2e2dc"
SERIES = [("cache_all", "prefix cache, all earlier epochs", "#8a5cd1", "-"),
          ("cache_last", "prefix cache, last epoch only", "#8a5cd1", "--"),
          ("spec1_all", "spec (top-1), all earlier epochs", "#1baf7a", "-"),
          ("spec1_last", "spec (top-1), last epoch only", "#1baf7a", "--")]
fig, ax = plt.subplots(figsize=(5.6, 4.2), dpi=200)
xs = [r["epoch"] for r in rows]
for key, label, col, ls in SERIES:
    ax.plot(xs, [100 * r[key] for r in rows], color=col, ls=ls, lw=2, marker="o", ms=7, mec="white", mew=1.5,
            label=label, zorder=3)
ax.set_xticks(xs)
ax.set_xticklabels([str(x) + ("\n(cold)" if x == 1 else "") for x in xs])
ax.set_xlabel("GRPO epoch", color=INK)
ax.set_ylabel("hit rate (% of steps)", color=INK)
ax.set_ylim(0, 100)
ax.set_xlim(min(xs) - 0.3, max(xs) + 0.3)
ax.grid(axis="y", color=GRID, lw=0.8)
ax.set_axisbelow(True)
for s in ("top", "right"):
    ax.spines[s].set_visible(False)
for s in ("left", "bottom"):
    ax.spines[s].set_color("#bdbdb5")
ax.tick_params(colors=MUTED, labelsize=8)
ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.01), ncol=2, fontsize=7.5, borderaxespad=0, handlelength=3.2)
fig.tight_layout()
for ext in ("png", "svg"):
    fig.savefig(os.path.join(out, f"hitrate_window.{ext}"))
print("wrote", os.path.join(out, "hitrate_window.png"))
