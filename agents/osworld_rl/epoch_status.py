"""Progress of the runs in an epoch folder (e.g. traces/motivation_2_timeline): one block per run.

  python3 epoch_status.py traces/motivation_2_timeline
"""
import collections, glob, json, sys, time
from pathlib import Path

G = 1024
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "traces/motivation_2_timeline")
runs = sorted((d for d in OUT.iterdir() if (d / "events.jsonl").exists()), key=lambda d: (d / "events.jsonl").stat().st_mtime)
print(f"  {OUT.name}   ({time.strftime('%H:%M')} UTC)\n")
for run in runs:
    cfg = json.load(open(run / "config.json"))
    events = [json.loads(l) for l in open(run / "events.jsonl")]
    mem = [json.loads(l) for l in open(run / "mem.jsonl")] if (run / "mem.jsonl").exists() else []
    by = collections.Counter(e["event"] for e in events)
    n = (cfg.get("groups") or 0) * cfg["rollouts"]
    done = by["run_done"] > 0
    errs = sum(1 for e in events if e["event"] == "rollout_done" and e["error"])
    calls = sum(sum(1 for _ in open(f)) for f in glob.glob(f"{run}/*/*__g*/chat.jsonl"))
    t1 = events[-1]["t"] if done else time.time()
    print(f"  {run.name:14s} {cfg['system']:6s} {'DONE' if done else 'RUNNING'}  {(t1 - events[0]['t']) / 60:5.1f} min"
          f"{'   (replay)' if cfg.get('replay') else '   (live model)'}")
    print(f"    rollouts {by['rollout_done']}/{n} done, {errs} errors | copies freed {by['copy_released']} | "
          f"model steps {calls} | clone retries {sum(1 for e in events if e['event'] in ('tfork_clone', 'ckpt_clone') and not e.get('ok', True))}")
    if mem:
        now = mem[-1]
        phases = ", ".join(f"{v} {k}" for k, v in collections.Counter(now["phases"].values()).most_common()) or "-"
        peak = lambda f: max(f(r) for r in mem) / G
        print(f"    {'at end' if done else 'now'}: {len(now['containers'])} envs, groups: {phases}")
        print(f"    memory GiB  host {now['host']['used_delta_mib'] / G:6.1f} (peak {peak(lambda r: r['host']['used_delta_mib']):6.1f})"
              f"   PSS {now['total']['pss_mib'] / G:6.1f} (peak {peak(lambda r: r['total']['pss_mib']):6.1f})"
              + (f"   working set {now['total'].get('cg_ws_mib', 0) / G:6.1f} (peak {peak(lambda r: r['total'].get('cg_ws_mib', 0)):6.1f})"
                 if any(r["total"].get("cg_ws_mib") for r in mem) else ""))
    print()
