"""Compare osw_run.py runs of the same replayed traces: time, throughput, memory, prefix-cache work, and whether every
rollout got the same reward and step count as the first run.

  python3 replay_compare.py traces/ld_nocache_ov1 traces/ld_nocache_ov0 traces/ld_disk traces/ld_tmpl
"""
import glob, json, statistics as st, sys
from pathlib import Path


def jl(p):
    return [json.loads(l) for l in open(p)] if Path(p).exists() else []


def med(v):
    return f"{st.median(v):.1f}" if v else "-"


ref = None
print(f"{'run':<16} {'wall min':>8} {'steps/s':>7} {'desk s/step':>11} {'peak ws GiB':>11} {'envs':>4} {'GiB/env':>7} "
      f"{'hits':>5} {'restores':>8} {'restore med s':>13} {'tmpl':>4} {'fork fail':>9} {'same as 1st':>11}")
for d in map(Path, sys.argv[1:]):
    ev, mem = jl(d / "events.jsonl"), jl(d / "mem.jsonl")
    done = [e for e in ev if e["event"] == "rollout_done"]
    res = {(e["task"], e["k"]): (e["reward"], e["steps"]) for e in done}
    ref = ref or res
    same = sum(res.get(k) == v for k, v in ref.items())
    wall = (max(e["t"] for e in done) - ev[0]["t"]) if done else 0
    steps = sum(e["steps"] for e in done)
    desk = [json.loads(l)["exec_s"] for f in glob.glob(f"{d}/*/*/traj.jsonl") for l in open(f)]
    peak = max(mem, key=lambda m: m["total"].get("cg_ws_mib", 0)) if mem else None
    ws = peak["total"].get("cg_ws_mib", 0) / 1024 if peak else 0
    envs = len(peak["containers"]) if peak else 0
    n = lambda k: sum(e["event"] == k for e in ev)
    forks = [e for e in ev if e["event"] == "prefix_fork"]
    print(f"{d.name:<16} {wall / 60:>8.1f} {steps / wall if wall else 0:>7.2f} {sum(desk) / max(len(desk), 1):>11.2f} "
          f"{ws:>11.1f} {envs:>4} {ws / max(envs, 1):>7.2f} {n('prefix_hit'):>5} {n('prefix_restored'):>8} "
          f"{med([e['secs'] for e in ev if e['event'] == 'prefix_restored']):>13} {n('prefix_template'):>4} "
          f"{sum(not e['ok'] for e in forks):>9} {f'{same}/{len(ref)}':>11}")
