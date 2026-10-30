"""Prefix-cache hits by tree depth (the step number a hit answered), one series per run (epoch): hit count, and hit rate
(hits / rollouts that reached that step). Grouped bars, one group per depth. Writes .png/.svg/.csv.

  <python with matplotlib> -I hits_by_depth.py --out <png> [--depth 8] <run dir>=<label> [...]
"""
import argparse, collections, csv, glob, json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import MaxNLocator, PercentFormatter

ap = argparse.ArgumentParser()
ap.add_argument("runs", nargs="+", help="<run dir>=<label>")
ap.add_argument("--out", required=True)
ap.add_argument("--depth", type=int, default=8)
a = ap.parse_args()

COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#eda100"]  # validate_palette.js: passes (light)
INK, MUTED, GRID, AXIS = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": AXIS, "axes.labelcolor": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})
series, rows = [], []
for spec in a.runs:
    run, label = spec.rsplit("=", 1)
    reached, hit = collections.Counter(), collections.Counter()
    for f in glob.glob(f"{run}/*/*__g*/traj.jsonl"):
        for s in (json.loads(l) for l in open(f) if l.strip()):
            if s["step_num"] <= a.depth:
                reached[s["step_num"]] += 1
                hit[s["step_num"]] += bool(s.get("lazy"))
    series.append((label, reached, hit))
    for n in range(1, a.depth + 1):
        rows.append({"run": label, "depth": n, "hits": hit[n], "reached": reached[n],
                     "hit_rate": round(hit[n] / reached[n], 4) if reached[n] else 0})
fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 3.8), dpi=200)
k, w = len(series), 0.8 / len(series)
xs = list(range(1, a.depth + 1))
for i, (label, reached, hit) in enumerate(series):
    off = [x - 0.4 + w * (i + 0.5) for x in xs]
    tot = sum(hit.values())
    ax1.bar(off, [hit[n] for n in xs], width=w, color=COLORS[i % len(COLORS)], edgecolor="#ffffff", linewidth=1,
            label=f"{label} ({tot} hits)")
    ax2.bar(off, [hit[n] / reached[n] if reached[n] else 0 for n in xs], width=w, color=COLORS[i % len(COLORS)],
            edgecolor="#ffffff", linewidth=1)
ax1.set_title("Hits by depth", loc="left", fontsize=10.5)
ax1.set_ylabel("hits (steps answered from the cache)")
ax1.yaxis.set_major_locator(MaxNLocator(integer=True))
ax2.set_title("Hit rate by depth (of rollouts that reached the step)", loc="left", fontsize=10.5)
ax2.set_ylabel("hit rate")
ax2.yaxis.set_major_formatter(PercentFormatter(1.0, decimals=0))
ax2.set_ylim(0, 1)
for ax in (ax1, ax2):
    ax.set_xlabel("tree depth (step number)")
    ax.set_xticks(xs)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
fig.legend(*ax1.get_legend_handles_labels(), frameon=False, loc="upper center", bbox_to_anchor=(0.5, 0.02), ncol=min(k, 5),
           fontsize=9)
fig.tight_layout()
fig.savefig(a.out, bbox_inches="tight")
fig.savefig(str(Path(a.out).with_suffix(".svg")), bbox_inches="tight")
with open(Path(a.out).with_suffix(".csv"), "w", newline="") as f:
    wr = csv.DictWriter(f, fieldnames=["run", "depth", "hits", "reached", "hit_rate"])
    wr.writeheader()
    wr.writerows(rows)
print("wrote", a.out)
