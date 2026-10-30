"""Hit rate per GRPO epoch with all earlier epochs as knowledge: prefix (screen) cache vs TAGE speculation.

  venv/bin/python hitrate_plot.py OUT_DIR EPOCH1_DIR EPOCH2_DIR ...

Epoch e uses epochs 1..e-1 as warm data (epoch 1: cold) plus what it learns during the epoch itself.
  prefix cache: steps whose (task, screen, action) is cached with the correct next screen (cache_epochs.py)
  spec top-1 / top-2: steps whose action is TAGE's first / first-two guess (tage_epochs.py)
Writes hitrate_epochs.png/.svg and hitrate_epochs.csv.
"""
import csv, os, sys

out, epochs = sys.argv[1], sys.argv[2:]
here = os.path.dirname(os.path.abspath(__file__))


def load(name):
    """score() from cache_epochs.py / tage_epochs.py (their printing part is not run)."""
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
    warm = epochs[:e - 1]
    _, _, right, _, _ = cache_score(warm, cur)
    _, top1, top2, _ = tage_score(warm, cur)
    rows.append(dict(epoch=e, trace=os.path.basename(cur), prefix_cache=right, spec_top1=top1, spec_top2=top2))
    print(f"epoch {e}: prefix cache {right:.1%} | spec top-1 {top1:.1%} | spec top-2 {top2:.1%}")

os.makedirs(out, exist_ok=True)
with open(os.path.join(out, "hitrate_epochs.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

INK, MUTED, GRID = "#1f1f1f", "#6b6b6b", "#e2e2dc"
SERIES = [("prefix_cache", "prefix cache", "#8a5cd1", "-"), ("spec_top2", "spec (top-2)", "#1baf7a", "--"),
          ("spec_top1", "spec (top-1)", "#1baf7a", "-")]

fig, ax = plt.subplots(figsize=(5.6, 4.0), dpi=200)
xs = [r["epoch"] for r in rows]
for key, label, col, ls in SERIES:
    ys = [100 * r[key] for r in rows]
    ax.plot(xs, ys, color=col, ls=ls, lw=2, marker="o", ms=7, mec="white", mew=1.5, label=label, zorder=3)
ax.set_xticks(xs)
ax.set_xticklabels([f"{x}\n" + ("(cold)" if x == 1 else f"(knows 1–{x - 1})" if x > 2 else "(knows 1)") for x in xs])
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
ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.01), ncol=3, fontsize=8, borderaxespad=0, handlelength=3.2)
fig.tight_layout()
for ext in ("png", "svg"):
    fig.savefig(os.path.join(out, f"hitrate_epochs.{ext}"))
print("wrote", os.path.join(out, "hitrate_epochs.png"))
