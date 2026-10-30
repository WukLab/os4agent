"""Performance of the in-memory prefix cache: replays of one recording with and without it, side by side.

  venv/bin/python -I pmem_report.py <run dir>... [--csv out.csv]

Per run: wall time (run_start -> run_done); boot + task setup time summed over groups, and groups that started from a
cached after-setup state instead; rollout time (mean, sum); execution time of all steps (traj exec_s) and of the
steps a hit could replace (step <= the cache depth); prefix saves (count, time), hits (count, time), evictions;
memory over the run from mem.jsonl: peak working set (cgroup) and PSS of the rollouts' environments, peak PSS of the
cached snapshots (containers owned by "cache"), their peak sum, and the host's used-memory delta.
"""
import argparse, collections, csv, glob, json, os
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("runs", nargs="+")
ap.add_argument("--csv")
a = ap.parse_args()


def jl(p):
    return [json.loads(l) for l in open(p) if l.strip()] if os.path.exists(p) else []


rows = []
for run in map(Path, a.runs):
    cfg, ev = json.load(open(run / "config.json")), jl(run / "events.jsonl")
    depth = cfg.get("prefix_depth", 3)
    t0 = next((e["t"] for e in ev if e["event"] == "run_start"), ev[0]["t"] if ev else 0)
    t1 = next((e["t"] for e in ev if e["event"] == "run_done"), ev[-1]["t"] if ev else 0)
    by = collections.defaultdict(list)
    for e in ev:
        by[e["event"]].append(e)
    steps = [s for f in glob.glob(f"{run}/*/*__g*/traj.jsonl") for s in jl(f)]
    peak = collections.defaultdict(float)
    for m in jl(run / "mem.jsonl"):
        env = [c for c in m["containers"].values() if c.get("t") != "cache"]
        cache = [c for c in m["containers"].values() if c.get("t") == "cache"]
        for k, v in (("env_ws_gib", sum(c.get("cg_ws_mib", 0) for c in env)), ("env_pss_gib", sum(c.get("pss_mib", 0) for c in env)),
                     ("cache_pss_gib", sum(c.get("pss_mib", 0) for c in cache)),
                     ("env_plus_cache_pss_gib", sum(c.get("pss_mib", 0) for c in env + cache)),
                     ("host_used_delta_gib", m["host"]["used_delta_mib"])):
            peak[k] = max(peak[k], v / 1024)
        peak["snapshots_max"] = max(peak["snapshots_max"], len(cache))
    rd = by["rollout_done"]
    r = {"run": run.name, "prefix_mem": cfg.get("prefix_mem", False), "budget_gib": cfg.get("prefix_mem_budget_gib"),
         "wall_min": round((t1 - t0) / 60, 1), "groups": len(by["group_done"]) + len(by["group_error"]),
         "boot_setup_s": round(sum(e.get("secs", 0) for e in by["boot"] + by["setup"]), 1),
         "groups_from_cache": len(by["setup_from_cache"]), "rollouts": len(rd),
         "rollout_mean_s": round(sum(e["secs"] for e in rd) / max(len(rd), 1), 1),
         "rollout_sum_min": round(sum(e["secs"] for e in rd) / 60, 1), "steps": len(steps),
         "exec_s_all": round(sum(s.get("exec_s", 0) for s in steps), 1),
         "exec_s_steps_le_depth": round(sum(s.get("exec_s", 0) for s in steps if s["step_num"] <= depth), 1),
         "saves": len(by["prefix_saved"]), "save_s": round(sum(e.get("secs", 0) for e in by["prefix_saved"]), 1),
         "hits": len(by["prefix_hit"]), "hit_s": round(sum(e.get("secs", 0) for e in by["prefix_hit"]), 1),
         "evictions": len(by["prefix_evict"]), "save_skipped": len(by["prefix_save_skipped"]),
         "failed_clone_attempts": sum(1 for e in ev if e["event"].endswith("_clone") and not e.get("ok", True)),
         "errors": sum(1 for e in rd if e.get("error")) + len(by["group_error"]),
         **{k: round(v, 2) if isinstance(v, float) else v for k, v in peak.items()}}
    rows.append(r)

keys = list(dict.fromkeys(k for r in rows for k in r))
w = max(len(k) for k in keys)
print(" " * w + "".join(f"  {r['run'][-22:]:>22s}" for r in rows))
for k in keys[1:]:
    print(f"{k:>{w}s}" + "".join(f"  {str(r.get(k, '')):>22s}" for r in rows))
if a.csv:
    with open(a.csv, "w", newline="") as f:
        cw = csv.DictWriter(f, fieldnames=keys)
        cw.writeheader()
        cw.writerows(rows)
