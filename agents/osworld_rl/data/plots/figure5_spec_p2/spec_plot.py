"""Speculation vs no speculation through one epoch (same recording replayed twice), styled like timeline_plot.py.

  python3 spec_plot.py OUT BASELINE_RUN SPEC_RUN [TASKPREFIX:K ...]   -> OUT/spec_memory.png/.svg, OUT/spec_batch.png/.svg

TASKPREFIX:K leaves that rollout out of the batch plot in both runs (e.g. 7a4e4bc8:0, whose 128 s same-cell drag ends
the epoch in every run).

memory: environments' cgroup working set (every live desktop, speculation copies included) over time
batch:  rollouts still running (the batch the model serves) over time
"""
import json, sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from timeline_plot import G, INK, MUTED, GRID, AXIS, load

LABEL = ("no speculation", "speculation (ours)")
COLOR = ("#eb6834", "#2a78d6")  # timeline_plot's validated slots 2 and 1


def style(ax, ylabel, loc="upper right"):
    ax.set_xlabel("time since the epoch started (min)")
    ax.set_ylabel(ylabel)
    ax.set_ylim(bottom=0)
    ax.set_xlim(left=0)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, loc=loc)


def save(fig, out, name):
    for ext in ("png", "svg"):
        fig.savefig(out / f"{name}.{ext}", bbox_inches="tight", pad_inches=0.15)
    plt.close(fig)


def main():
    out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    runs = [load(r) for r in sys.argv[2:4]]
    skip = [(x.split(":")[0], int(x.split(":")[1])) for x in sys.argv[4:]]
    kept = lambda e: not any(e["task"].startswith(t) and e["k"] == k for t, k in skip)
    plt.rcParams.update({"font.size": 11, "axes.edgecolor": AXIS, "axes.labelcolor": INK,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})

    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=200)
    for (_, t0, _, mem), lab, col in zip(runs, LABEL, COLOR):
        xs = [(r["t"] - t0) / 60 for r in mem]
        ys = [r["total"].get("cg_ws_mib", 0) / G for r in mem]
        i = ys.index(max(ys))
        ax.plot(xs, ys, color=col, lw=2, label=f"{lab} (peak {ys[i]:.0f} GiB)")
        print(f"{lab}: peak working set {max(ys):.1f} GiB at {xs[i]:.1f} min")
    style(ax, "environments' working set (GiB)", loc=(0.2, 0.05))
    save(fig, out, "spec_memory")

    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=200)
    ins = ax.inset_axes([0.12, 0.1, 0.36, 0.38])  # the tail, where the two differ
    for (_, t0, events, _), lab, col in zip(runs, LABEL, COLOR):
        n = sum(1 for e in events if e["event"] == "rollout_done" and kept(e))
        ends = sorted((e["t"] - t0) / 60 for e in events if e["event"] == "rollout_done" and kept(e))
        start = min((e["t"] - t0) / 60 for e in events if e["event"] == "fork")  # first rollouts begin
        xs, ys = [0, start], [0, n]
        for i, x in enumerate(ends):
            xs.append(x); ys.append(n - i - 1)
        ax.step(xs, ys, where="post", color=col, lw=2, label=f"{lab} (99% done {ends[int(n * .99) - 1]:.1f} min)")
        ins.step(xs, ys, where="post", color=col, lw=1.6)
        print(f"{lab}: last rollout {ends[-1]:.2f} min, 99% done {ends[int(n * .99) - 1]:.2f} min")
    style(ax, "rollouts still running (batch size)")
    tmax = max(max((e["t"] - t0) / 60 for e in ev if e["event"] == "rollout_done" and kept(e)) for _, t0, ev, _ in runs)
    ins.set_xlim(14, tmax + 0.2); ins.set_ylim(0, 25)
    ins.set_title("tail", fontsize=9, color=MUTED, pad=2)
    ins.tick_params(labelsize=8)
    ins.grid(axis="y", color=GRID, lw=0.6)
    for side in ("top", "right"):
        ins.spines[side].set_visible(False)
    save(fig, out, "spec_batch")
    batch_log(out, runs, kept)


def batch_log(out, runs, kept):
    """Rollouts still running on a log axis: each halving of the batch gets the same height, so the tail is readable."""
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=200)
    for (_, t0, events, _), lab, col in zip(runs, LABEL, COLOR):
        ends = sorted((e["t"] - t0) / 60 for e in events if e["event"] == "rollout_done" and kept(e))
        n = len(ends)
        start = min((e["t"] - t0) / 60 for e in events if e["event"] == "fork")
        xs, ys = [start], [n]
        for i, x in enumerate(ends[:-1]):
            xs.append(x); ys.append(n - i - 1)
        xs.append(ends[-1]); ys.append(1)
        ax.step(xs, ys, where="post", color=col, lw=2, label=f"{lab} (last done {ends[-1]:.1f} min)")
        ax.plot([ends[-1]], [1], marker="o", ms=6, color=col, mec="white", mew=1.5, zorder=3)
    ax.set_yscale("log", base=2)
    ax.set_yticks([1, 2, 4, 8, 16, 32, 64, 128])
    ax.set_yticklabels(["1", "2", "4", "8", "16", "32", "64", "128"])
    ax.set_ylim(0.8, 160)
    ax.set_xlabel("time since the epoch started (min)")
    ax.set_ylabel("rollouts still running (batch size, log)")
    ax.set_xlim(left=0)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, loc="lower left")
    save(fig, out, "spec_batch_log")


if __name__ == "__main__":
    main()
