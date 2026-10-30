"""Memory over time from osw_run.py's mem.jsonl (one sample every few seconds): the live desktops' working set (cgroup
memory minus inactive file pages, summed) and PSS, the cache snapshots' PSS, the host's used memory over the run's
start, and the number of live desktops. One line per run and metric; writes .png/.svg/.csv.

  <python with matplotlib> -I mem_timeline.py --out <png> <run dir>=<label> [...]
"""
import argparse, csv, json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ap = argparse.ArgumentParser()
ap.add_argument("runs", nargs="+", help="<run dir>=<label>")
ap.add_argument("--out", required=True)
ap.add_argument("--pss", action="store_true", help="PSS only: live desktops, cache snapshots, and their sum")
ap.add_argument("--desktop-pss", action="store_true", help="only the live desktops' PSS")
ap.add_argument("--cache-line", action="store_true", help="with --desktop-pss: also the cache snapshots' PSS")
ap.add_argument("--stack-cache", action="store_true",
                help="with --desktop-pss: the cache snapshots' PSS stacked on the desktops' (line = desktops + snapshots, band shaded)")
ap.add_argument("--top-only", action="store_true", help="the GiB panel alone, without the live-desktops panel")
ap.add_argument("--counts", action="store_true", help="one panel: live desktops and live cache snapshots (counts)")
a = ap.parse_args()

COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#6250d6"]
INK, MUTED, GRID, AXIS = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": AXIS, "axes.labelcolor": INK,
                     "xtick.color": MUTED, "ytick.color": MUTED, "text.color": INK})
rows, series = [], []
for spec in a.runs:
    run, label = spec.rsplit("=", 1)
    ev = [json.loads(l) for l in open(Path(run) / "events.jsonl") if l.strip()]
    t0 = next(e["t"] for e in ev if e["event"] == "run_start")
    pts = []
    for m in (json.loads(l) for l in open(Path(run) / "mem.jsonl") if l.strip()):
        env = [c for c in m["containers"].values() if c.get("t") != "cache"]
        cache = [c for c in m["containers"].values() if c.get("t") == "cache"]
        r = {"run": label, "minutes": round((m["t"] - t0) / 60, 3), "desktops": len(env), "snapshots": len(cache),
             "env_ws_gib": round(sum(c.get("cg_ws_mib", 0) for c in env) / 1024, 2),
             "env_pss_gib": round(sum(c.get("pss_mib", 0) for c in env) / 1024, 2),
             "cache_pss_gib": round(sum(c.get("pss_mib", 0) for c in cache) / 1024, 2),
             "total_pss_gib": round(sum(c.get("pss_mib", 0) for c in env + cache) / 1024, 2),
             "host_used_delta_gib": round(m["host"]["used_delta_mib"] / 1024, 2)}
        pts.append(r)
        rows.append(r)
    series.append((label, pts))


def save(fig):
    fig.savefig(a.out, bbox_inches="tight")
    fig.savefig(str(Path(a.out).with_suffix(".svg")), bbox_inches="tight")
    with open(Path(a.out).with_suffix(".csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("wrote", a.out)


def tidy(ax):
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    ax.set_ylim(bottom=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


if a.counts:
    fig, ax = plt.subplots(figsize=(8, 3.6), dpi=200)
    for i, (label, pts) in enumerate(series):
        col = COLORS[i % len(COLORS)]
        x = [p["minutes"] for p in pts]
        ax.plot(x, [p["desktops"] for p in pts], "-", color=col, lw=2,
                label=f"{label}: live desktops (peak {max(p['desktops'] for p in pts)})")
        if any(p["snapshots"] for p in pts):
            ax.plot(x, [p["snapshots"] for p in pts], ":", color=col, lw=2,
                    label=f"{label}: cache snapshots (peak {max(p['snapshots'] for p in pts)})")
    ax.set_ylabel("count")
    ax.set_xlabel("time since the epoch started (min)")
    ax.set_title("Live desktops and cache snapshots over the epoch", loc="left", fontsize=10.5)
    tidy(ax)
    fig.tight_layout()
    fig.legend(*ax.get_legend_handles_labels(), frameon=False, loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=1, fontsize=8.5)
    save(fig)
    raise SystemExit
if a.top_only:
    fig, ax1 = plt.subplots(figsize=(8, 4.4), dpi=200)
    ax2 = None
else:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(8, 6.4), dpi=200, sharex=True, gridspec_kw={"height_ratios": [3, 1.4]})
styles = [("env_ws_gib", "-", "live desktops, working set"), ("env_pss_gib", "--", "live desktops, PSS"),
          ("cache_pss_gib", ":", "cache snapshots, PSS")]
if a.pss:
    styles = [("total_pss_gib", "-", "live desktops + cache snapshots, PSS"), ("env_pss_gib", "--", "live desktops, PSS"),
              ("cache_pss_gib", ":", "cache snapshots, PSS")]
if a.desktop_pss:
    styles = [("env_pss_gib", "-", "live desktops, PSS")] + ([("cache_pss_gib", ":", "cache snapshots, PSS")] if a.cache_line else [])
for i, (label, pts) in enumerate(series):
    col = COLORS[i % len(COLORS)]
    x = [p["minutes"] for p in pts]
    for key, ls, what in styles:
        if key in ("cache_pss_gib", "total_pss_gib") and not any(p["cache_pss_gib"] for p in pts):  # no cache: total = desktops
            continue
        ax1.plot(x, [p[key] for p in pts], ls, color=col, lw=2, label=f"{label}: {what} (peak {max(p[key] for p in pts):.0f} GiB)")
    if a.stack_cache and any(p["cache_pss_gib"] for p in pts):
        lo, hi = [p["env_pss_gib"] for p in pts], [p["total_pss_gib"] for p in pts]
        ax1.fill_between(x, lo, hi, color=col, alpha=0.15, lw=0, label=f"{label}: cache snapshots, PSS (band)")
        ax1.plot(x, hi, "--", color=col, lw=2, label=f"{label}: live desktops + cache snapshots, PSS (peak {max(hi):.0f} GiB)")
    if ax2:
        ax2.plot(x, [p["desktops"] for p in pts], "-", color=col, lw=2, label=label)
ax1.set_ylabel("GiB")
ax1.set_title("Memory over the epoch", loc="left", fontsize=10.5)
(ax2 or ax1).set_xlabel("time since the epoch started (min)")
if ax2:
    ax2.set_ylabel("live desktops")
for ax in (ax1, ax2) if ax2 else (ax1,):
    tidy(ax)
fig.tight_layout()
fig.legend(*ax1.get_legend_handles_labels(), frameon=False, loc="upper center", bbox_to_anchor=(0.5, 0.0), ncol=1, fontsize=8.5)
save(fig)
