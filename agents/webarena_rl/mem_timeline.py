"""Environments' working set over the epoch, one line per system (the OSWorld figure's style), x in minutes since the
epoch started. Runs: wa_record.py recordings and / or wa_replay.py replays.
  <python with matplotlib> -I mem_timeline.py --out <png> <run dir>=<system> [<run dir>=<system> ...] [--detail]
<system>: tfork, criu, aenv or nofork (a recording: a fresh environment per rollout). Working set = sum over the
environments' cgroups (each counted once) of memory.current - inactive_file, as kubelet / cAdvisor define it and as
agents/osworld_rl/scale_plot.py uses; for aenv (all VMs in one cgroup) the aenv-server cgroup's, minus its charge at
run start (run_start aenv_baseline). --detail: instead, one panel per run with the stacked cgroup split (anon / shmem /
page cache / kernel), host used dashed (reference only), live environments below, wave setup shaded. Also writes
<out>.svg. --cut <system>=<minutes>: end that system's line at its last sample at or before <minutes>, drawn down to 0
there (e.g. to leave out a run's flat tail of one straggler group). --csv <path>: also the plotted series for a
spreadsheet: per system a time (min) and a working set (GiB) column, row i = sample i, blank after a series ends."""
import argparse, csv, json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("runs", nargs="+", help="<run dir>=<system>")
ap.add_argument("--out", required=True)
ap.add_argument("--detail", action="store_true")
ap.add_argument("--direct-labels", action="store_true", help="also name each line at its peak")
ap.add_argument("--csv", help="also write the plotted series here")
ap.add_argument("--cut", action="append", default=[], help="<system>=<minutes>")
a = ap.parse_args()

LABEL = {"tfork": "tfork (ours)", "criu": "CRIU", "aenv": "AgentENV", "nofork": "no fork (fresh env per rollout)"}
COLOR = {"tfork": "#2a78d6", "criu": "#eb6834", "aenv": "#1baf7a", "nofork": "#eda100"}  # as the OSWorld figure
STACK = {"anon": "#2a78d6", "shmem": "#1baf7a", "file": "#eb6834", "kernel": "#6250d6"}
INK, MUTED, GRID, AXIS = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7"


def load(run):
    R = Path(run)
    ev = [json.loads(l) for l in open(R / "events.jsonl")]
    t0 = next(e["t"] for e in ev if e["event"] == "run_start")
    base = next((e.get("aenv_baseline") for e in ev if e["event"] == "run_start"), None)
    rows = []
    for l in open(R / "mem.jsonl"):
        m = json.loads(l)
        if "aenv_server" in m:   # AENV: every VM is in aenv-server's cgroup; minus its idle charge at run start
            sv = m["aenv_server"]
            d = lambda k: (sv.get(k, 0) - (base or {}).get(k, 0)) / 1024
            rows.append({"x": (m["t"] - t0) / 60, "ws": d("cg_ws_mib"), "cur": d("cg_mib"), "anon": d("cg_anon_mib"),
                         "shmem": d("cg_shmem_mib"), "file": d("cg_file_mib") - d("cg_shmem_mib"),
                         "kernel": d("cg_kernel_mib"), "host": m["host"]["used_mib"] / 1024, "envs": m["envs"]})
            continue
        cgs = {}
        for name, c in m["containers"].items():
            cgs.setdefault(c.get("cg", name), c)   # a cgroup counted once
        g = lambda k: sum(c.get(k, 0) or 0 for c in cgs.values()) / 1024
        rows.append({"x": (m["t"] - t0) / 60, "ws": g("cg_ws_mib"), "cur": g("cg_mib"), "anon": g("cg_anon_mib"),
                     "shmem": g("cg_shmem_mib"), "file": g("cg_file_mib") - g("cg_shmem_mib"),   # v2 file includes shmem
                     "kernel": g("cg_kernel_mib"), "host": m["host"]["used_mib"] / 1024, "envs": len(cgs)})
    setup, s = [], None
    for e in ev:
        if e["event"] == "wave_setup_start":
            s = (e["t"] - t0) / 60
        elif e["event"] == "wave_setup_done" and s is not None:
            setup.append((s, (e["t"] - t0) / 60))
    return rows, setup


runs = [(r.rsplit("=", 1)[0], r.rsplit("=", 1)[1]) for r in a.runs]
data = [(sysn, *load(d)) for d, sysn in runs]
cut = {k: float(v) for k, v in (c.split("=") for c in a.cut)}
for i, (sysn, rows, setup) in enumerate(data):
    if sysn in cut:
        rows = [r for r in rows if r["x"] <= cut[sysn]]
        rows.append({**rows[-1], **dict.fromkeys(("ws", "cur", "anon", "shmem", "file", "kernel", "envs"), 0)})
        data[i] = (sysn, rows, setup)
if a.csv:
    with open(a.csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([f"{LABEL[sysn]} {c}" for sysn, _, _ in data for c in ("time (min)", "working set (GiB)")])
        for i in range(max(len(rows) for _, rows, _ in data)):
            w.writerow([v for _, rows, _ in data
                        for v in ((f"{rows[i]['x']:.3f}", f"{rows[i]['ws']:.2f}") if i < len(rows) else ("", ""))])
plt.rcParams.update({"font.size": 11, "axes.edgecolor": AXIS, "axes.labelcolor": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})


def style(ax):
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


if not a.detail:
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=200)
    for sysn, rows, _ in data:
        x, y = [r["x"] for r in rows], [r["ws"] for r in rows]
        ax.plot(x, y, color=COLOR[sysn], lw=2, label=LABEL[sysn], zorder=3)
        if a.direct_labels:   # off by default: overlapping peaks put a label on another system's line
            pk = max(rows, key=lambda r: r["ws"])
            ax.annotate(LABEL[sysn].split(" (fresh")[0], (pk["x"], pk["ws"]), xytext=(0, 6), textcoords="offset points",
                        ha="center", va="bottom", fontsize=10, color=INK)
    ax.set_xlim(0, max(r["x"] for _, rows, _ in data for r in rows) * 1.02)
    ax.set_ylim(0, max(r["ws"] for _, rows, _ in data for r in rows) * 1.4)   # headroom: legend above the peaks
    ax.set_xlabel("time since the epoch started (min)")
    ax.set_ylabel("environments' working set (GiB)")
    style(ax)
    ax.legend(frameon=False, loc="upper right")
else:
    n = len(data)
    ymax = max(max(r["host"], r["cur"]) for _, rows, _ in data for r in rows) * 1.12
    fig, axes = plt.subplots(2 * n, 1, figsize=(11, 4.2 * n), sharex=True, dpi=150,
                             gridspec_kw={"height_ratios": [3, 1] * n, "hspace": 0.35})
    for i, (sysn, rows, setup) in enumerate(data):
        ax, ae = axes[2 * i], axes[2 * i + 1]
        x = [r["x"] for r in rows]
        ax.stackplot(x, *[[r[k] for r in rows] for k in STACK], colors=list(STACK.values()), labels=list(STACK),
                     alpha=0.85, linewidth=0)
        ax.plot(x, [r["ws"] for r in rows], color=INK, lw=1.5, label="working set (current − inactive_file)")
        ax.plot(x, [r["host"] for r in rows], color=MUTED, lw=1.2, ls="--", label="host used (reference)")
        pk = max(rows, key=lambda r: r["cur"])
        ax.annotate(f"peak {pk['cur']:.1f} GiB\n{pk['envs']} envs, {pk['x']:.1f} min", (pk["x"], pk["cur"]),
                    xytext=(10, -30), textcoords="offset points", fontsize=9, color=INK,
                    bbox={"fc": "white", "ec": "none", "alpha": 0.8, "pad": 1.5})
        for s, e in setup:
            for axx in (ax, ae):
                axx.axvspan(s, e, color=GRID, alpha=0.6, lw=0, zorder=0)
        ax.set_ylim(0, ymax)
        ax.set_ylabel("GiB (env cgroups)")
        ax.set_title(f"{LABEL[sysn]}: memory of all environments (shaded: wave setup)", loc="left", fontsize=11)
        ae.step(x, [r["envs"] for r in rows], where="post", color=COLOR[sysn], lw=1.5)
        ae.set_ylabel("live envs")
        ae.set_ylim(0, max(r["envs"] for r in rows) * 1.2 + 1)
        style(ax), style(ae)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", ncol=6, fontsize=9, frameon=False, bbox_to_anchor=(0.5, 1.0 + 0.02 / n))
    axes[-1].set_xlabel("time since the epoch started (min)")
fig.tight_layout()
fig.savefig(a.out, bbox_inches="tight")
fig.savefig(str(Path(a.out).with_suffix(".svg")), bbox_inches="tight")
print("wrote", a.out)
