"""Markdown index of result dirs: python3 run_index.py data/traces > data/RUNS.md (osw_run.py and wa_replay.py dirs)."""
import json, sys, time
from pathlib import Path

DEFAULTS = {"rollouts": 8, "max_steps": 15, "parallel": 0, "fork_concurrency": 4, "replay_latency": 1.0, "spec": "off",
            "spec_exec": 0, "screen_cache": 0, "tree_cache": "", "base_fork": 0, "release_copies": 0, "temperature": 1.0, "overlay_rootfs": 1, "full_memcopy": 1}
SHOW = ["max_steps", "parallel", "fork_concurrency", "base_fork", "release_copies", "replay_latency", "spec", "spec_exec",
        "spec_max_forks", "spec_slow", "spec_inplace", "spec_prefork", "screen_cache", "tree_cache", "prefix_cache",
        "overlay_rootfs", "full_memcopy", "clone_concurrency", "log_rows"]

print("| run | start (PDT) | system | tasks | replay of | flags | rollouts | reward>0 | wall min |")
print("|---|---|---|---|---|---|---|---|---|")
for d in sorted(Path(sys.argv[1]).iterdir(), key=lambda p: p.name):
    if not d.is_dir() or not ((d / "config.json").exists() or (d / "events.jsonl").exists()):
        continue
    cfg = json.load(open(d / "config.json")) if (d / "config.json").exists() else {}
    ev = [json.loads(l) for l in open(d / "events.jsonl") if l.strip()] if (d / "events.jsonl").exists() else []
    ts = [e["t"] for e in ev if "t" in e]
    start = time.strftime("%m-%d %H:%M", time.localtime(ts[0])) if ts else ""
    wall = f"{(ts[-1] - ts[0]) / 60:.1f}" if len(ts) > 1 else ""
    done = [e for e in ev if e.get("event") == "rollout_done"]
    pos = sum(1 for e in done if (e.get("reward") or 0) > 0)
    if not done and (d / "rewards.tsv").exists():  # older dirs: rewards from result.txt
        rows = [l.split("\t") for l in open(d / "rewards.tsv") if "\t" in l]
        done = rows
        pos = sum(1 for r in rows if r[1].strip() not in ("", "0", "0.0"))
    flags = " ".join(f"{k}={cfg[k]}" for k in SHOW if cfg.get(k, DEFAULTS.get(k, 0)) not in (DEFAULTS.get(k, 0), "", None, "off"))
    rep = Path(str(cfg.get("replay") or cfg.get("trace_dir") or "")).name
    print(f"| {d.name} | {start} | {cfg.get('system', '')} | {Path(str(cfg.get('tasks', ''))).name} | {rep} | {flags} | "
          f"{len(done)} | {pos} | {wall} |")
