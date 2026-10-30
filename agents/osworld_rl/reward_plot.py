"""GRPO reward curve from an osw_loop.py experiment: mean rollout reward per epoch.

  python3 reward_plot.py pod_backup/<exp>      -> <dir>/reward_curve.png/.svg and reward_curve.csv

Reads <exp>_loop.jsonl (one line per epoch). An epoch whose groups all had identical rewards trained nothing (marked).
"""
import json, sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

d = Path(sys.argv[1])
rows = [json.loads(l) for l in open(next(d.glob("*_loop.jsonl")))]
rows = [r for r in rows if r.get("mean_reward") is not None]
with open(d / "reward_curve.csv", "w") as f:
    f.write("epoch,policy,rollouts,mean_reward,successes,trained_samples,groups_used,skipped\n")
    for r in rows:
        f.write(f"{r['epoch']},{r['served']},{r['rollouts']},{r['mean_reward']:.4f},{r['successes']},"
                f"{r.get('trained', '')},{r.get('groups_used', '')},{bool(r.get('skipped') or r.get('stopped'))}\n")

INK, MUTED, GRID, AXIS, BLUE = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7", "#2a78d6"
plt.rcParams.update({"font.size": 11, "axes.edgecolor": AXIS, "axes.labelcolor": INK, "xtick.color": MUTED,
                     "ytick.color": MUTED, "text.color": INK})
fig, ax = plt.subplots(figsize=(6.4, 4.0), dpi=200)
xs = [r["epoch"] for r in rows]
ys = [r["mean_reward"] for r in rows]
ax.plot(xs, ys, color=BLUE, lw=2, marker="o", ms=6, mec="white", mew=1.5, label="mean reward")
skip = [(r["epoch"], r["mean_reward"]) for r in rows if r.get("skipped") or r.get("stopped")]
if skip:
    ax.plot(*zip(*skip), ls="none", marker="o", ms=9, mfc="none", mec=MUTED, mew=1.5, label="no update (no reward variance)")
ax.set_xlabel("epoch")
ax.set_ylabel("mean rollout reward")
ax.set_xticks(xs)
ax.set_ylim(bottom=0)
ax.grid(axis="y", color=GRID, lw=0.8)
ax.set_axisbelow(True)
for side in ("top", "right"):
    ax.spines[side].set_visible(False)
ax.legend(frameon=False, loc="upper left")
for ext in ("png", "svg"):
    fig.savefig(d / f"reward_curve.{ext}", bbox_inches="tight", pad_inches=0.15)
print(open(d / "reward_curve.csv").read())
