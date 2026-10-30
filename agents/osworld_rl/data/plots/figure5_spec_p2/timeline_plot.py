"""Memory over time through one epoch of rollouts, one line per system.

  python3 timeline_plot.py OUT RUN [RUN ...]      -> OUT/timeline.csv, OUT/timeline_<metric>.png/.svg

Time is measured from each run's start. Metrics (GiB), all from mem.jsonl:
  host   host used memory above the run's starting baseline (MemTotal - MemAvailable); works for every system
  pss    sum of PSS over every live environment (AENV: the Firecracker process); works for every system
  ws     cgroup working set (memory.current - inactive_file): summed over containers for tfork / CRIU; for AENV the
         aenv-server container's cgroup, which every Firecracker VM is charged to
Also prints, per run, the peak of each metric and how many rollout copies were alive over time.
"""
import json, sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

G = 1024
LABEL = {"tfork": "tfork (ours)", "criu": "CRIU", "stock-criu": "stock CRIU", "aenv": "AgentENV"}
COLOR = {"tfork": "#2a78d6", "criu": "#eb6834", "aenv": "#1baf7a", "stock-criu": "#eda100"}  # validated slots 1-4
INK, MUTED, GRID, AXIS = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7"
METRICS = {"host": ("host memory used above baseline (GiB)", lambda r: r["host"]["used_delta_mib"]),
           "pss": ("environments' memory, PSS (GiB)", lambda r: r["total"]["pss_mib"]),
           "ws": ("environments' working set (GiB)", lambda r: r["total"].get("cg_ws_mib", 0))}


def load(run):
    run = Path(run)
    cfg = json.load(open(run / "config.json"))
    events = [json.loads(l) for l in open(run / "events.jsonl")]
    mem = [json.loads(l) for l in open(run / "mem.jsonl")]
    t0 = events[0]["t"]
    return cfg["system"], t0, events, mem


def main():
    out, runs = Path(sys.argv[1]), [load(r) for r in sys.argv[2:]]
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "timeline.csv", "w") as f:
        f.write("system,minutes,envs,host_gib,pss_gib,ws_gib\n")
        for system, t0, events, mem in runs:
            for r in mem:
                f.write(f"{system},{(r['t'] - t0) / 60:.3f},{len(r['containers'])},"
                        + ",".join(f"{fn(r) / G:.3f}" for _, fn in METRICS.values()) + "\n")
            copies = [e for e in events if e["event"] == "copy_released"]
            ends = sorted((e["t"] - t0) / 60 for e in events if e["event"] == "rollout_done")
            print(f"{system:6s} peaks: " + ", ".join(f"{k} {max(fn(r) for r in mem) / G:.2f}" for k, (_, fn) in METRICS.items())
                  + f" GiB | rollouts ended {ends[0]:.1f}-{ends[-1]:.1f} min | copies released early: {len(copies)}"
                  if ends else f"{system}: no rollouts finished")

    plt.rcParams.update({"font.size": 11, "axes.edgecolor": AXIS, "axes.labelcolor": INK,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})
    for key, (ylabel, fn) in METRICS.items():
        # runs recorded before AENV's cgroup was sampled have no working set: leave them out of that plot
        series = [(s, t0, mem) for s, t0, _, mem in runs if key != "ws" or any(r["total"].get("cg_ws_mib") for r in mem)]
        if not series:
            continue
        fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=200)
        for system, t0, mem in series:
            xs = [(r["t"] - t0) / 60 for r in mem]
            ys = [fn(r) / G for r in mem]
            ax.plot(xs, ys, color=COLOR.get(system, INK), lw=2, label=LABEL.get(system, system))
            ax.annotate(LABEL.get(system, system), (xs[ys.index(max(ys))], max(ys)), xytext=(4, 6),
                        textcoords="offset points", fontsize=10, color=INK)
        ax.set_xlabel("time since the epoch started (min)")
        ax.set_ylabel(ylabel)
        ax.set_ylim(bottom=0)
        ax.set_xlim(left=0)
        ax.grid(axis="y", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        if len(series) > 1:
            ax.legend(frameon=False, loc="upper right")
        for ext in ("png", "svg"):
            fig.savefig(out / f"timeline_{key}.{ext}", bbox_inches="tight", pad_inches=0.15)
        plt.close(fig)


if __name__ == "__main__":
    main()
