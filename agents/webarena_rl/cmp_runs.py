"""Per run: epoch, peak working set (aenv: server cgroup minus baseline), fork per group, actions, timeouts, rewards,
last groups, slowest rollouts / steps.   python3 -I cmp_runs.py <run dir> ...  """
import json, sys, statistics as st
from pathlib import Path
for d in sys.argv[1:]:
    R = Path(d); ev = [json.loads(l) for l in open(R / "events.jsonl")]
    t0 = next(e["t"] for e in ev if e["event"] == "run_start"); t1 = next(e["t"] for e in ev if e["event"] == "run_done")
    base = next(e.get("aenv_baseline") for e in ev if e["event"] == "run_start") or {}
    pk = (0, 0, 0); emax = 0
    for l in open(R / "mem.jsonl"):
        m = json.loads(l); emax = max(emax, m["envs"])
        ws = (m["aenv_server"]["cg_ws_mib"] - base.get("cg_ws_mib", 0)) / 1024 if "aenv_server" in m else \
            sum(c.get("cg_ws_mib", 0) for c in {c.get("cg", n): c for n, c in m["containers"].items()}.values()) / 1024
        if ws > pk[0]: pk = (ws, m["envs"], (m["t"] - t0) / 60)
    clone = [e["clone_s"] for e in ev if e["event"] == "clone_done"]
    ro = [e for e in ev if e["event"] == "rollout_done"]
    acts, errs, tos, slow = [], 0, 0, []
    for sf in R.glob("*__g*/steps.jsonl"):
        for l in open(sf):
            s = json.loads(l)
            if "t_act_end" not in s: continue
            a = s["t_act_end"] - s["t_act_start"]; acts.append(a)
            er = s.get("error")
            if er: errs += 1; tos += "Timeout" in er
            slow.append((a, sf.parent.name, s["step"], s["action"].get("action"), (er or "")[:70]))
    acts.sort(); q = lambda p: acts[int(p * (len(acts) - 1))]
    done = sorted(((e["t"] - t0) / 60, e["task"]) for e in ev if e["event"] == "group_done")
    print(f"== {R.name}\n epoch {(t1 - t0) / 60:.1f} min; peak ws {pk[0]:.1f} GiB ({pk[1]} envs, {pk[2]:.1f} min; {emax} max)")
    print(f" fork/group median {st.median(clone):.1f} s; rollouts {len(ro)}, errors {sum(1 for e in ro if e['error'])}, "
          f"unscored {sum(1 for e in ro if e['reward'] is None)}, rewards changed {sum(1 for e in ro if e['reward'] != e['reward_rec'])}")
    print(f" rollout s median {st.median(e['secs'] for e in ro):.1f}, max {max(e['secs'] for e in ro):.0f}; actions median {q(.5):.2f} "
          f"p90 {q(.9):.1f} max {acts[-1]:.0f} s over {len(acts)}; action errors {errs} (timeouts {tos})")
    print(" last groups done (min, task):", ", ".join(f"{t:.1f} {k}" for t, k in done[-4:]))
    print(" slowest rollouts:", ", ".join(f"{e['task']}__g{e['k']} {e['secs']:.0f}s" for e in sorted(ro, key=lambda e: -e["secs"])[:5]))
    print(" slowest steps:", *[f"\n   {a:.0f}s {n} step {k} {t} {er}" for a, n, k, t, er in sorted(slow, reverse=True)[:6]])
