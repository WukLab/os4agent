"""Per-task success rate (reward >= 0.9 over the task's rollouts), no speculation vs speculation, same recording replayed.

  python3 spec_reward.py OUT BASELINE_RUN SPEC_RUN   -> OUT/spec_reward.png/.svg, OUT/rewards.csv
"""
import json, sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from timeline_plot import INK, MUTED, GRID, AXIS
from spec_plot import LABEL, COLOR


NAMES = {"3ef2b351": "Writer: center heading", "8ba5ae7a": "VLC: recordings folder", "12086550": "Chrome: passwords page",
         "357ef137": "Calc: hours x rate", "4188d3a4": "Calc: freeze panes", "d53ff5ee": "Writer: lowercase",
         "b4f95342": "Chrome: recreation.gov", "42e0a640": "Calc: sums to Sheet2", "1273e544": "Calc: copy column",
         "030eeff7": "Chrome: Do Not Track", "1954cced": "Calc: pivot table", "26a8440e": "Calc: monthly totals",
         "5d901039": "Impress: stretch image", "7a4e4bc8": "Calc: reorder columns", "7dbc52a6": "Impress: note + bold",
         "e246f6d8": "Writer: italics to 14pt"}


def rewards(run):
    out = defaultdict(dict)
    for e in map(json.loads, open(Path(run) / "events.jsonl")):
        if e["event"] == "rollout_done":
            out[e["task"]][e["k"]] = e["reward"]
    return out


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    runs = [rewards(r) for r in sys.argv[2:4]]
    tasks = json.load(open(Path(sys.argv[2]) / "config.json")).get("tasks_list") or None
    apps = {}
    for run in sys.argv[2:4]:
        for e in map(json.loads, open(Path(run) / "events.jsonl")):
            if e["event"] == "rollout_done" and "app" in e:
                apps[e["task"]] = e["app"]
    order = sorted(runs[0], key=lambda t: (-sum(v >= 0.9 for v in runs[0][t].values()), t))
    rate = [[sum(v >= 0.9 for v in r[t].values()) / max(len(r[t]), 1) for t in order] for r in runs]
    with open(out / "rewards.csv", "w") as f:
        f.write("task,k," + ",".join(l.replace(" ", "_") for l in LABEL) + "\n")
        for t in order:
            for k in sorted(runs[0][t]):
                f.write(f"{t},{k}," + ",".join(str(r[t].get(k, '')) for r in runs) + "\n")
    same = sum(runs[0][t].get(k) == runs[1][t].get(k) for t in order for k in runs[0][t])
    n = sum(len(runs[0][t]) for t in order)
    print(f"identical rewards: {same}/{n}; solved: " + ", ".join(f"{l} {sum(v >= 0.9 for t in order for v in r[t].values())}" for l, r in zip(LABEL, runs)))

    plt.rcParams.update({"font.size": 11, "axes.edgecolor": AXIS, "axes.labelcolor": INK,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})
    fig, ax = plt.subplots(figsize=(7.2, 4.6), dpi=200)
    w = 0.38
    xs = range(len(order))
    for j, (vals, lab, col) in enumerate(zip(rate, LABEL, COLOR)):
        solved = sum(v >= 0.9 for t in order for v in runs[j][t].values())
        ax.bar([x + (j - 0.5) * w for x in xs], [100 * v for v in vals], width=w - 0.04, color=col,
               label=f"{lab} ({solved}/{n} solved)")
    ax.set_xticks(list(xs))
    ax.set_xticklabels([NAMES.get(t[:8], t[:8]) for t in order], rotation=60, ha="right", fontsize=8)
    ax.set_ylabel("tasks' success rate (% of 8 rollouts)")
    ax.set_xlabel("task")
    ax.set_ylim(0, 105)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, loc="upper right")
    for ext in ("png", "svg"):
        fig.savefig(out / f"spec_reward.{ext}", bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


if __name__ == "__main__":
    main()
