"""Where an epoch's time goes, from the per-step logs of osw_run.py: each rollout's wall time split into the first
observation, model decode (chat.jsonl llm_start..llm_end), desktop steps (traj exec_s minus the cache work inside it),
lazy hits, materializations and prefix saves (step_events.py), the checker (t_eval..t_end) and the
rest; then the groups (8 rollouts of a task): boot/setup/fork before the rollouts, the straggler, the slots.

  <python> -I timeline_breakdown.py <run dir>[=<label>] [...] [--csv out.csv] [--plot out.png]   (--plot needs matplotlib)
"""
import argparse, collections, csv, glob, json, os, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from step_events import attribute  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("runs", nargs="+")
ap.add_argument("--csv")
ap.add_argument("--plot", help="png: mean rollout time by part, and the slot that finished last")
ap.add_argument("--depth", type=int, default=2, help="steps counted as the cached prefix")
a = ap.parse_args()


def jl(p):
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []


PARTS = ["obs0", "llm", "env_prefix", "env_rest", "hit", "materialize", "save", "eval", "other"]
out_rows, plot = [], []
for spec in a.runs:
    run, label = spec.rsplit("=", 1) if "=" in spec else (spec, Path(spec).name)
    run = Path(run)
    ev = jl(run / "events.jsonl")
    t0 = next(e["t"] for e in ev if e["event"] == "run_start")
    t1 = next(e["t"] for e in ev if e["event"] == "run_done")
    by = collections.defaultdict(list)
    for e in ev:
        by[e["event"]].append(e)
    dirs = [Path(f).parent for f in sorted(glob.glob(f"{run}/*/*__g*/traj.jsonl"))]
    info = [(d, d.name.rsplit("__g", 1)[0], jl(d / "traj.jsonl"), jl(d / "chat.jsonl"), json.load(open(d / "timing.json"))) for d in dirs]
    cache, left = attribute(str(run), info)  # materialize / save seconds by (rollout dir, step)

    roll, steps_env = [], collections.defaultdict(list)
    for d, task, tr, ch, tm in info:
        k = d.name.rsplit("__g", 1)[1]
        p = dict.fromkeys(PARTS, 0.0)
        p["obs0"] = ch[0]["t"]["obs"] - tm["t_start"] if ch and "t" in ch[0] else 0  # (old replays: no timing)
        for s, c in zip(tr, ch):
            p["llm"] += c["t"]["llm_end"] - c["t"]["llm_start"] if "t" in c else 0
            if s.get("lazy"):
                p["hit"] += s["exec_s"]
                continue
            m, sv = cache[(d, s["step_num"])]["materialize"], cache[(d, s["step_num"])]["save"]
            env = max(0.0, s["exec_s"] - m - sv)
            p["materialize"] += m
            p["save"] += sv
            p["env_prefix" if s["step_num"] <= a.depth else "env_rest"] += env
            steps_env[d.parent.name].append(env)
        if tm.get("t_eval"):  # a materialization at the episode end happens just before t_eval
            p["materialize"] += cache[(d, "end")]["materialize"]
            p["eval"] = tm["t_end"] - tm["t_eval"]
        wall = tm["t_end"] - tm["t_start"]
        p["other"] = wall - sum(p.values())
        roll.append({"task": task, "k": int(k), "domain": d.parent.name, "start": tm["t_start"] - t0, "end": tm["t_end"] - t0,
                     "wall": wall, "steps": len(tr), "lazy_steps": sum(1 for s in tr if s.get("lazy")), **p})

    # groups: start = boot start or setup_from_cache; rollouts start after the fork; end = group_done
    g_start = {}
    for e in by["boot"]:
        g_start[e["task"]] = e["t"] - e["secs"] - t0
    for e in by["setup_from_cache"]:
        g_start[e["task"]] = e["t"] - t0
    g_end = {e["task"]: e["t"] - t0 for e in by["group_done"]}
    groups = []
    for task, s in g_start.items():
        rs = [r for r in roll if r["task"] == task]
        if not rs or task not in g_end:
            continue
        first, strag = min(r["start"] for r in rs), max(rs, key=lambda r: r["end"])
        groups.append({"task": task, "domain": rs[0]["domain"], "start": s, "pre": first - s, "straggler": strag["wall"],
                       "straggler_steps": strag["steps"], "mean_rollout": sum(r["wall"] for r in rs) / len(rs),
                       "post": g_end[task] - strag["end"], "end": g_end[task], "strag": strag})
    groups.sort(key=lambda g: g["start"])
    # slots: --parallel groups at once; a later group takes the slot of the group that finished just before it started
    slots, free = [], []
    for g in groups:
        done = sorted((s[-1]["end"], i) for i, s in enumerate(slots) if s[-1]["end"] <= g["start"] + 1 and i not in free)
        if len(slots) < 8 and not done:
            slots.append([g])
        else:
            i = max(done)[1] if done else min(range(len(slots)), key=lambda i: slots[i][-1]["end"])
            slots[i].append(g)

    n = len(roll)
    tot = {k: sum(r[k] for r in roll) for k in PARTS}
    wall_sum = sum(r["wall"] for r in roll)
    print(f"\n=== {run.name}: wall {(t1 - t0) / 60:.1f} min, {n} rollouts, {sum(r['steps'] for r in roll)} steps "
          f"({sum(r['lazy_steps'] for r in roll)} lazy hits), rollout time {wall_sum / 60:.0f} min"
          + (f", {left} materializations/saves unmatched" if left else ""))
    print("  rollout time by part (min, % of rollout time, per rollout s):")
    for k in PARTS:
        print(f"    {k:12s} {tot[k] / 60:7.1f}  {100 * tot[k] / wall_sum:5.1f}%  {tot[k] / n:6.1f}")
    for dom, xs in sorted(steps_env.items()):
        xs = sorted(xs)
        print(f"  desktop step {dom:17s} n={len(xs):4d} mean {sum(xs) / len(xs):5.1f} s  p50 {xs[len(xs) // 2]:5.1f}  p90 {xs[int(len(xs) * .9)]:5.1f}")
    print(f"  groups: pre-rollout (boot+setup+fork) mean {sum(g['pre'] for g in groups) / len(groups):5.1f} s, "
          f"straggler {sum(g['straggler'] for g in groups) / len(groups):5.1f} s vs mean rollout "
          f"{sum(g['mean_rollout'] for g in groups) / len(groups):5.1f} s, after straggler {sum(g['post'] for g in groups) / len(groups):4.1f} s")
    for i, s in enumerate(slots):
        chain = "  ->  ".join(f"{g['domain'][:6]}:{g['task'][:8]} pre {g['pre']:3.0f} strag {g['straggler']:4.0f}s/{g['straggler_steps']}st" for g in s)
        print(f"  slot {i}: ends {s[-1]['end'] / 60:5.1f} min | {chain}")
    crit = max(slots, key=lambda s: s[-1]["end"])
    print(f"  critical slot: start of first group {crit[0]['start']:.0f} s; for each group (pre, straggler parts):")
    for g in crit:
        st = g["strag"]
        print(f"    {g['task'][:8]} {g['domain']:17s} start {g['start']:5.0f} pre {g['pre']:4.0f} straggler k{st['k']} {st['steps']} steps "
              + " ".join(f"{k} {st[k]:.0f}" for k in PARTS if abs(st[k]) >= 0.5))
    plot.append({"label": label, "wall": (t1 - t0) / 60, "per": {k: tot[k] / n for k in PARTS}, "crit": crit})
    for g in groups:
        out_rows.append({"run": run.name, **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in g.items() if k != "strag"}})
    for r in roll:
        out_rows.append({"run": run.name, "rollout": f"{r['task'][:8]}__g{r['k']}",
                         **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()}})
if a.csv:
    keys = list(dict.fromkeys(k for r in out_rows for k in r))
    with open(a.csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(out_rows)

if a.plot:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    INK, MUTED, GRID, AXIS, SURF = "#0b0b0b", "#898781", "#e1e0d9", "#c3c2b7", "#ffffff"
    plt.rcParams.update({"font.size": 10, "axes.edgecolor": AXIS, "axes.labelcolor": INK,
                         "xtick.color": MUTED, "ytick.color": INK, "text.color": INK})
    SEGS = [("first observation", ["obs0"], "#eda100"), ("model decode", ["llm"], "#6250d6"),
            (f"steps 1-{a.depth} on the desktop (lazy hits ~0)", ["env_prefix", "hit"], "#1baf7a"),
            (f"steps {a.depth + 1}+ on the desktop", ["env_rest"], "#2a78d6"), ("materialize (fork at first miss)", ["materialize"], "#eb6834"),
            ("prefix save", ["save"], "#d63a8a"), ("checker + other", ["eval", "other"], "#b5b3ab")]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(7.2, 5.6), dpi=200, gridspec_kw={"height_ratios": [len(plot), len(plot)], "hspace": 0.9})
    ys = list(range(len(plot)))[::-1]
    for y, r in zip(ys, plot):
        x = 0
        for name, keys, col in SEGS:
            v = sum(r["per"][k] for k in keys)
            ax1.barh(y, v, left=x, height=0.62, color=col, edgecolor=SURF, linewidth=1, label=name if y == ys[0] else None)
            if v >= 12:
                ax1.text(x + v / 2, y, f"{v:.0f}", ha="center", va="center", fontsize=7.5, color=SURF if col not in ("#eda100", "#1baf7a", "#b5b3ab") else INK)
            x += v
        ax1.text(x + 3, y, f"{x:.0f} s", va="center", fontsize=8.5, color=INK)
    ax1.set_yticks(ys, [r["label"] for r in plot])
    ax1.set_xlabel("mean time per rollout (s)")
    ax1.set_title("Where a rollout's time goes", loc="left", fontsize=10.5)
    ax1.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.45, -0.32), ncol=3, fontsize=7.5)
    for y, r in zip(ys, plot):  # the slot that ended last: each group's boot/setup/fork, then its 8 rollouts until the straggler
        for g in r["crit"]:
            ax2.barh(y, g["pre"], left=g["start"], height=0.62, color="#5f5e5a", edgecolor=SURF, linewidth=1)
            ax2.barh(y, g["end"] - g["start"] - g["pre"], left=g["start"] + g["pre"], height=0.62, color="#2a78d6", edgecolor=SURF, linewidth=1)
            ax2.text(g["start"] + g["pre"] + 6, y, f"{g['domain'].replace('libreoffice_', '')} {g['task'][:6]}",
                     va="center", fontsize=7.5, color=SURF)
            ax2.text(g["start"] + g["pre"] / 2, y + 0.42, f"{g['pre']:.0f}", ha="center", va="bottom", fontsize=7.5, color=INK)
        ax2.text(r["crit"][-1]["end"] + 6, y, f"{r['wall']:.1f} min", va="center", fontsize=8.5)
    ax2.set_yticks(ys, [r["label"] for r in plot])
    ax2.set_xlabel("time since the epoch started (s)")
    ax2.set_title("The slot that finished last: boot/setup/fork (gray, s), then the group's rollouts (blue)", loc="left", fontsize=10.5)
    for ax in (ax1, ax2):
        ax.grid(axis="x", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    xm = max(r["crit"][-1]["end"] for r in plot)
    ax2.set_xlim(0, xm * 1.12)
    ax2.set_ylim(-0.6, len(plot) - 0.2)
    fig.savefig(a.plot, bbox_inches="tight")
    print("wrote", a.plot)
