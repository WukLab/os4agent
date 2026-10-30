"""Plot peak memory vs. concurrent rollouts from a scale_mem.sh sweep.

  python3 scale_plot.py traces/scale        -> traces/scale/scale.csv, scale.png/.svg, scale_unreclaimable.png/.svg
  python3 scale_plot.py OUT DIR1 DIR2 ...   -> the same for several sweeps in one plot, written to OUT

One CSV row per run. Two plots, each summed over every environment's cgroup at the run's peak:
  scale             working set: memory.current minus inactive page cache (the kubelet / cAdvisor measure)
  scale_unreclaimable  anon + shmem (tmpfs) + kernel: memory the kernel cannot drop; leaves out all page cache, so
                    it doesn't count the per-copy cache of binaries CRIU copies keep (each has its own rootfs)
The CSV also has peak cgroup charge, PSS and the host's used-memory delta. Per system the line is the mean over task
subsets (the bar spans min to max), with a dashed line at the host's RAM and an x where a system hit the memory limit.
"""
import collections, json, re, statistics as st, sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "traces/scale")
SWEEPS = [Path(d) for d in sys.argv[2:]] or [OUT]
LABEL = {"tfork": "tfork (ours)", "criu": "CRIU",
         "tfork+base": "tfork, shared base desktop", "criu+base": "CRIU, shared base desktop"}
COLOR = {"tfork": "#2a78d6", "criu": "#eb6834"}  # categorical slots 1-2, validated for CVD and contrast
DASH = {False: "-", True: (0, (4, 2))}  # the base-desktop variant is the same hue, dashed
INK, MUTED, GRID, AXIS = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7"


def unreclaimable(sample):
    t = sample["total"]
    return t["cg_anon_mib"] + t["cg_shmem_mib"] + t["cg_kernel_mib"]


def summarize(run):
    events = [json.loads(l) for l in open(run / "events.jsonl")]
    mem = [json.loads(l) for l in open(run / "mem.jsonl")]
    kinds = collections.Counter(e["event"] for e in events)
    ok = sum(1 for e in events if e["event"] == "rollout_done" and not e["error"])
    forks = [e["secs"] for e in events if e["event"] == "fork"]
    sys_, n, seed = re.match(r"(\w+)_n(\d+)_s(\d+)$", run.name).groups()
    base = bool(json.load(open(run / "config.json")).get("base_fork", 0))
    return {"system": sys_ + ("+base" if base else ""), "n": int(n), "seed": int(seed),
            "peak_ws_gib": round(max(r["total"].get("cg_ws_mib", 0) for r in mem) / 1024, 2),
            "peak_unreclaimable_gib": round(max(unreclaimable(r) for r in mem) / 1024, 2),
            "peak_cgroup_gib": round(max(r["total"]["cg_mib"] for r in mem) / 1024, 2),
            "peak_pss_gib": round(max(r["total"]["pss_mib"] for r in mem) / 1024, 2),
            "peak_host_used_gib": round(max(r["host"]["used_delta_mib"] for r in mem) / 1024, 2),
            "host_total_gib": round((mem[0]["host"]["used_mib"] + mem[0]["host"]["avail_mib"]) / 1024),
            "mem_limit": kinds["mem_limit"] > 0, "finished": kinds["run_done"] > 0,
            "rollouts_ok": ok, "rollouts": n, "group_errors": kinds["group_error"],
            "fork_s_median": round(st.median(forks), 1) if forks else None,
            "minutes": round((mem[-1]["t"] - mem[0]["t"]) / 60, 1)}


def main():
    rows = [summarize(d) for sw in SWEEPS for d in sorted(sw.glob("*_n*_s*")) if d.is_dir() and (d / "mem.jsonl").exists()]
    rows = [r for r in rows if r["finished"] or r["mem_limit"]]  # a run still in progress has no peak yet
    if not rows:
        raise SystemExit(f"no runs under {OUT}")
    cols = list(rows[0])
    with open(OUT / "scale.csv", "w") as f:
        f.write(",".join(cols) + "\n")
        for r in sorted(rows, key=lambda r: (r["system"], r["n"], r["seed"])):
            f.write(",".join(str(r[c]) for c in cols) + "\n")
    draw(rows, "peak_ws_gib", "peak memory in use (GiB)", "scale")
    draw(rows, "peak_unreclaimable_gib", "peak unreclaimable memory (GiB)", "scale_unreclaimable")
    print(open(OUT / "scale.csv").read())


def draw(rows, Y, ylabel, name):
    plt.rcParams.update({"font.size": 11, "axes.edgecolor": AXIS, "axes.labelcolor": INK,
                         "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=200)
    systems = [s for s in LABEL if any(r["system"] == s for r in rows)]
    both_variants = len({"+base" in s for s in systems}) == 2  # only then do dashes and long labels carry meaning
    label = lambda s: LABEL[s] if both_variants else LABEL[s.split("+")[0]]

    top = 0
    for system in systems:
        by_n = collections.defaultdict(list)
        for r in rows:
            if r["system"] == system:
                by_n[r["n"]].append(r)
        ok = {n: rs for n, rs in by_n.items() if not any(r["mem_limit"] for r in rs)}
        xs = sorted(ok)
        ys = [st.mean(r[Y] for r in ok[n]) for n in xs]
        lo = [y - min(r[Y] for r in ok[n]) for y, n in zip(ys, xs)]
        hi = [max(r[Y] for r in ok[n]) - y for y, n in zip(ys, xs)]
        top = max([top, *(y + h for y, h in zip(ys, hi))])
        c = COLOR[system.split("+")[0]]
        ax.errorbar(xs, ys, yerr=[lo, hi], color=c, lw=2, ls=DASH[both_variants and "+base" in system], marker="o", ms=6,
                    mec="white", mew=1.5, capsize=0, elinewidth=1.5, label=label(system), zorder=3)
        if xs:
            ax.annotate(label(system), (xs[-1], ys[-1]), xytext=(8, 0), textcoords="offset points",
                        va="center", fontsize=10, color=INK)
        for n, rs in by_n.items():
            if n not in ok:  # stopped at the memory limit: mark where, at the memory it had reached
                y = max(r[Y] for r in rs)
                top = max(top, y)
                ax.plot([n], [y], marker="X", ms=10, color=c, mec="white", mew=1, zorder=4)
                ax.annotate("out of memory", (n, y), xytext=(0, 9), textcoords="offset points",
                            ha="center", fontsize=9, color=INK)

    ymax = 256 if top <= 240 else 64 * -(-top * 1.08 // 64)  # 256 GiB unless the data needs more, in 64 GiB steps
    host = max(r["host_total_gib"] for r in rows)
    if host <= ymax:  # draw the RAM line only when it is in view
        ax.axhline(host, color=MUTED, lw=1, ls=(0, (4, 3)), zorder=1)
        ax.text(sorted({r["n"] for r in rows})[-1], host, f"host RAM ({host} GiB)", color=MUTED, va="bottom", ha="right", fontsize=9)
    sizes = sorted({r["n"] for r in rows})
    ax.set_xscale("log", base=2)
    ax.set_xticks(sizes, [str(n) for n in sizes])
    ax.minorticks_off()
    ax.set_ylim(0, ymax)
    ax.set_yticks(range(0, int(ymax) + 1, 64 if ymax <= 512 else 128))
    ax.set_xlabel("concurrent rollouts (batch size × 8)")
    ax.set_ylabel(ylabel)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.legend(frameon=False, loc="upper left")
    for ext in ("png", "svg"):
        fig.savefig(OUT / f"{name}.{ext}", bbox_inches="tight", pad_inches=0.15)  # room for the direct labels
    plt.close(fig)


if __name__ == "__main__":
    main()
