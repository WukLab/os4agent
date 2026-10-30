"""Several runs of the same recording on one plot each: working set, rollouts still running (linear + log).
Styled like timeline_plot.py / spec_plot.py.

  python3 sys_plot.py OUT SUFFIX LABEL=RUN[:TASKPREFIX:K] ...   -> OUT/spec_{memory,batch,batch_log}_SUFFIX.png/.svg

TASKPREFIX:K leaves that rollout out of that run's batch curves (memory keeps it).
"""
import json, sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from timeline_plot import G, INK, MUTED, GRID, AXIS, load

COLORS = {"CRIU": "#eb6834", "tfork": "#2a78d6", "tfork + speculation (ours)": "#1baf7a", "AgentENV": "#eda100"}


def style(ax, ylabel, loc):
    ax.set_xlabel("time since the epoch started (min)")
    ax.set_ylabel(ylabel)
    ax.set_xlim(left=0)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, loc="lower left", bbox_to_anchor=(0, 1.01), borderaxespad=0)  # above the axes: no data there


def save(fig, out, name):
    for ext in ("png", "svg"):
        fig.savefig(out / f"{name}.{ext}", bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def main():
    out, suffix = Path(sys.argv[1]), sys.argv[2]
    out.mkdir(parents=True, exist_ok=True)
    runs = []
    for arg in sys.argv[3:]:
        label, spec = arg.split("=", 1)
        parts = spec.split(":")
        skip = (parts[1], int(parts[2])) if len(parts) == 3 else None
        runs.append((label, load(parts[0]), skip))
    plt.rcParams.update({"font.size": 11, "axes.edgecolor": AXIS, "axes.labelcolor": INK,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})

    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=200)
    for label, (_, t0, events, mem), skip in runs:
        kept = lambda e: not (skip and e["task"].startswith(skip[0]) and e["k"] == skip[1])
        ends = sorted((e["t"] - t0) / 60 for e in events if e["event"] == "rollout_done" and kept(e))
        xs = [(r["t"] - t0) / 60 for r in mem]
        ys = [r["total"].get("cg_ws_mib", 0) / G for r in mem]
        cut = [i for i, x in enumerate(xs) if x <= ends[-2]]  # the line ends when one rollout is left; a dot marks the end
        col = COLORS.get(label, INK)
        ax.plot([xs[i] for i in cut], [ys[i] for i in cut], color=col, lw=2, label=f"{label} (peak {max(ys):.0f} GiB)")
        ax.plot([ends[-1]], [ys[cut[-1]]], marker="o", ms=6, color=col, mec="white", mew=1.5, zorder=3)
        print(f"{label}: peak working set {max(ys):.1f} GiB, last rollout {ends[-1]:.1f} min")
    ax.set_ylim(bottom=0)
    style(ax, "environments' working set (GiB)", (0.16, 0.03))
    save(fig, out, f"spec_memory_{suffix}")

    curves = []
    for label, (_, t0, events, _), skip in runs:
        kept = lambda e: not (skip and e["task"].startswith(skip[0]) and e["k"] == skip[1])
        ends = sorted((e["t"] - t0) / 60 for e in events if e["event"] == "rollout_done" and kept(e))
        start = min((e["t"] - t0) / 60 for e in events if e["event"] == "fork")
        curves.append((label, ends, start))
        print(f"{label}: last rollout {ends[-1]:.2f} min, 99% done {ends[int(len(ends) * .99) - 1]:.2f} min")
    for log in (False, True):
        fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=200)
        for label, ends, start in curves:
            n = len(ends)
            xs, ys = ([start], [n]) if log else ([0, start], [0, n])
            for i, x in enumerate(ends[:-1]):  # the line stops when one rollout is left; a dot marks when it finishes
                xs.append(x); ys.append(n - i - 1)
            col = COLORS.get(label, INK)
            ax.step(xs, ys, where="post", color=col, lw=2, label=f"{label} (last done {ends[-1]:.1f} min)")
            ax.plot([ends[-1]], [1], marker="o", ms=6, color=col, mec="white", mew=1.5, zorder=3)
        if log:
            ax.set_yscale("log", base=2)
            ax.set_yticks([1, 2, 4, 8, 16, 32, 64, 128]); ax.set_yticklabels(["1", "2", "4", "8", "16", "32", "64", "128"])
            ax.set_ylim(0.8, 160)
        else:
            ax.set_ylim(bottom=0)
        style(ax, "rollouts still running (batch size" + (", log)" if log else ")"), "lower left" if log else (0.03, 0.03))
        save(fig, out, f"spec_batch{'_log' if log else ''}_{suffix}")


if __name__ == "__main__":
    main()
