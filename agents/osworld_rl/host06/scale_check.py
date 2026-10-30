"""Progress and sanity checks for a scale_mem.sh sweep.

  python3 scale_check.py traces/motivation_1_peak_memory

Prints a table of finished runs, a line for the run in progress, and a warning for anything that looks wrong:
missing or failed groups and rollouts, environments not all alive at the sync points, inconsistent metrics, a peak
outside the rollouts, per-group memory drifting across sizes, or tfork not below CRIU.
"""
import collections, json, re, sys, time
from pathlib import Path

G = 1024
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "traces/scale")
warns = []


def warn(run, msg):
    warns.append(f"    ! {run}: {msg}")


def load(run):
    events = [json.loads(l) for l in open(run / "events.jsonl")]
    mem = [json.loads(l) for l in open(run / "mem.jsonl")] if (run / "mem.jsonl").exists() else []
    by = collections.defaultdict(list)
    for e in events:
        by[e["event"]].append(e)
    return events, mem, by


def running(name, n, groups, events, mem, by):
    if not mem:
        return f"{name}: starting"
    now = mem[-1]
    phases = ", ".join(f"{v} in {k}" for k, v in collections.Counter(now["phases"].values()).most_common()) or "none started"
    errs = sum(1 for e in by["rollout_done"] if e["error"])
    peak = max(r["total"].get("cg_ws_mib", 0) for r in mem) / G
    return (f"{name}: {(now['t'] - events[0]['t']) / 60:.1f} min, {groups} groups: {phases}\n"
            f"    envs alive {len(now['containers'])} (expect {groups * 9}, +1 with a base desktop), working set {now['total'].get('cg_ws_mib', 0) / G:.2f} GiB "
            f"(peak {peak:.2f}), rollouts {len(by['rollout_done'])}/{n} done, {errs} errors")


def finished(name, n, groups, mem, by, base):
    """Run the checks; -> (table row, per-group working set). base: the run forked its sources from one desktop."""
    if by["mem_limit"]:
        return f"stopped at the memory limit ({by['mem_limit'][0]['used_gib']} GiB used)", None
    if by["group_error"]:
        warn(name, f"{len(by['group_error'])} group errors: {by['group_error'][0]['error'][:100]}")
    if len(by["fork"]) != groups or any(e["copies"] != 8 for e in by["fork"]):
        warn(name, f"only {len(by['fork'])}/{groups} groups forked 8 copies")
    bad = sum(1 for e in by["rollout_done"] if e["error"])
    if len(by["rollout_done"]) != n or bad:
        warn(name, f"rollouts {len(by['rollout_done'])}/{n}, {bad} with errors")
    retries = sum(1 for k in ("tfork_clone", "ckpt_clone") for e in by[k] if not e.get("ok", True))
    if retries:
        warn(name, f"{retries} clone attempts failed and were retried")
    snaps = {ev: by[ev][0] for ev in ("all_forked", "all_done") if by[ev]}
    for ev in ("all_forked", "all_done"):
        if ev not in snaps:
            warn(name, f"no {ev} snapshot")
        elif len(snaps[ev]["containers"]) != groups * 9 + base:
            warn(name, f"{ev}: {len(snaps[ev]['containers'])}/{groups * 9 + base} envs alive")

    peak = max(mem, key=lambda r: r["total"].get("cg_ws_mib", 0))
    t = peak["total"]
    if t["cg_ws_mib"] > t["cg_mib"] + 1:
        warn(name, "working set above the cgroup charge")
    if abs(t["pss_anon_mib"] - t["cg_anon_mib"]) > 0.1 * t["cg_anon_mib"] + 64:
        warn(name, f"PSS anon {t['pss_anon_mib'] / G:.2f} and cgroup anon {t['cg_anon_mib'] / G:.2f} GiB disagree")
    phase = collections.Counter(peak["phases"].values()).most_common(1)
    phase = phase[0][0] if phase else "?"
    if phase not in ("rollouts", "teardown"):
        warn(name, f"peak happened during {phase}, not the rollouts")
    done = snaps.get("all_done", {}).get("total", {})
    if done and done.get("cg_ws_mib", 0) < 0.85 * t["cg_ws_mib"]:
        warn(name, f"end-of-rollouts working set {done['cg_ws_mib'] / G:.1f} is well below the peak {t['cg_ws_mib'] / G:.1f} GiB")

    src = copy = 0.0
    if "all_forked" in snaps and not base:  # copies are named by container id, or <source>-k<i>
        envs = snaps["all_forked"]["containers"]
        src = sum(c["cg_ws_mib"] for k, c in envs.items() if k.startswith("osw-") and "-k" not in k) / G / groups
        copy = (sum(c["cg_ws_mib"] for c in envs.values()) / G / groups - src) / 8
    per_group = t["cg_ws_mib"] / G / groups
    row = (f"{t['cg_ws_mib'] / G:7.2f} {t['cg_mib'] / G:7.2f} {t['pss_mib'] / G:6.2f} {peak['host']['used_delta_mib'] / G:6.2f}"
           f"  | {per_group:6.2f} {src:6.2f} {copy:5.2f}  | {n - bad:>4}/{n}")
    return row, per_group


def planned():
    """Runs the sweep will make, from its sweep.txt: one per system and size."""
    try:
        line = next(l for l in open(OUT / "sweep.txt") if l.startswith("sizes="))
    except (OSError, StopIteration):
        return None
    sizes = re.search(r"sizes=([\d ]+?) systems", line)[1].split()
    systems = re.search(r"systems=(.+?) limit_gib", line)[1].split()
    return len(systems) * len(sizes)


def main():
    runs = [r for r in OUT.glob("*_n*_s*") if r.is_dir() and (r / "events.jsonl").exists()]
    runs.sort(key=lambda p: (p.name.split("_")[0] != "tfork", int(re.search(r"_n(\d+)", p.name)[1]), p.name))
    rows, live, per_group = [], [], collections.defaultdict(dict)
    for run in runs:
        sys_, n, seed = re.match(r"(\w+)_n(\d+)_s(\d+)$", run.name).groups()
        n, groups = int(n), int(n) // 8
        events, mem, by = load(run)
        name = f"{sys_} N={n} s{seed}"
        if not by["run_done"]:
            live.append(running(name, n, groups, events, mem, by))
            continue
        base = int(json.load(open(run / "config.json")).get("base_fork", 0))
        row, pg = finished(name, n, groups, mem, by, base)
        rows.append(f"  {sys_:6s} {n:5d} {seed:>2}  | {row}")
        if pg is not None:
            per_group[sys_].setdefault(n, []).append(pg)

    for sys_, d in per_group.items():
        vals = [sum(v) / len(v) for _, v in sorted(d.items())]
        if len(vals) > 1 and max(vals) > 1.6 * min(vals):
            warn(sys_, f"per-group working set varies {min(vals):.2f}-{max(vals):.2f} GiB across sizes")
    for n in sorted(set(per_group.get("tfork", {})) & set(per_group.get("criu", {}))):
        t, c = (sum(per_group[s][n]) / len(per_group[s][n]) for s in ("tfork", "criu"))
        if t >= c:
            warn(f"N={n}", f"tfork per group {t:.2f} >= CRIU {c:.2f} GiB")

    total = planned()
    print(f"  {OUT.name}: {len(rows)}{f' of {total}' if total else ''} runs finished   ({time.strftime('%H:%M')} UTC)\n")
    print("                   | peak memory, GiB               | per group, GiB       | rollouts")
    print("  system     N  s  | working  cgroup    PSS   host  |  total source  copy  |   ok")
    print("  " + "-" * 82)
    print("\n".join(rows) if rows else "  (none yet)")
    print("\n  running:\n    " + "\n    ".join(live) if live else "\n  running: nothing")
    print("\n  checks: " + ("all OK" if not warns else f"{len(warns)} warnings\n" + "\n".join(warns)))
    print("\n  working = cgroup working set (memory.current - inactive_file), the plotted value.")
    print("  source / copy = working set right after the fork; total = at the peak.")


if __name__ == "__main__":
    main()
