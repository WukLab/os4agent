"""Per-epoch reward, rollouts, throughput, memory and prefix-cache stats of osw_loop.py experiments, side by side.

  python3 rl_report.py grpo_tfork16 grpo_tfork16_pfx [--epochs 5]    -> table on stdout + results/rl_report.csv

Reads pod_backup/<exp>/<exp>_loop.jsonl and traces/<exp>_e<N>/{events,mem}.jsonl.
"""
import argparse, json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("exps", nargs="+")
ap.add_argument("--epochs", type=int, default=0, help="only the first N epochs (0 = all)")
a = ap.parse_args()
HERE = Path(__file__).resolve().parent
G = 1024
COLS = ["exp", "epoch", "mean_reward", "successes", "rollouts", "steps", "rollout_min", "train_s", "rollouts_per_min",
        "steps_per_s", "peak_host_gib", "peak_ws_gib", "envs_at_peak", "ws_gib_per_env", "prefix_hits", "hit_frac",
        "restores", "saves", "save_fail", "restore_fail"]


def jl(p):
    return [json.loads(l) for l in open(p)] if p.exists() else []


rows = []
for exp in a.exps:
    for r in jl(HERE / "pod_backup" / exp / f"{exp}_loop.jsonl"):
        if a.epochs and r["epoch"] >= a.epochs:
            continue
        run = HERE / "traces" / r["run"]
        ev, mem = jl(run / "events.jsonl"), jl(run / "mem.jsonl")
        n = lambda name: sum(e["event"] == name for e in ev)
        steps = sum(e.get("steps") or 0 for e in ev if e["event"] == "rollout_done")
        peak = max(mem, key=lambda m: m["total"].get("cg_ws_mib", 0)) if mem else None
        ws = peak["total"].get("cg_ws_mib", 0) / G if peak else 0
        envs = len(peak["containers"]) if peak else 0
        secs = r["rollout_secs"]
        rows.append(dict(exp=exp, epoch=r["epoch"], mean_reward=round(r["mean_reward"], 4), successes=r["successes"],
                         rollouts=r["rollouts"], steps=steps, rollout_min=round(secs / 60, 1),
                         train_s=round(r.get("train_secs") or 0), rollouts_per_min=round(r["rollouts"] / secs * 60, 2),
                         steps_per_s=round(steps / secs, 2),
                         peak_host_gib=round(max((m["host"]["used_delta_mib"] for m in mem), default=0) / G, 1),
                         peak_ws_gib=round(ws, 1), envs_at_peak=envs, ws_gib_per_env=round(ws / envs, 2) if envs else 0,
                         prefix_hits=n("prefix_hit"), hit_frac=round(n("prefix_hit") / steps, 3) if steps else 0,
                         restores=n("prefix_restored"), saves=n("prefix_saved"), save_fail=n("prefix_save_failed"),
                         restore_fail=n("prefix_restore_failed")))

out = HERE / "results" / "rl_report.csv"
out.parent.mkdir(exist_ok=True)
with open(out, "w") as f:
    f.write(",".join(COLS) + "\n")
    for r in rows:
        f.write(",".join(str(r[c]) for c in COLS) + "\n")
w = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in COLS} if rows else {}
print("  ".join(c.rjust(w[c]) for c in COLS))
for r in rows:
    print("  ".join(str(r[c]).rjust(w[c]) for c in COLS))
print(f"-> {out}")
