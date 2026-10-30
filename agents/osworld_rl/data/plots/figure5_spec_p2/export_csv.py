"""Figure 5 data export: working set over time and rollout finish times, A (no speculation) vs P2 (speculation)."""
import json
F = "traces/figure5_spec_p2"
RUNS = (("r128_A", "no_speculation"), ("r128_P2", "speculation"))
with open(f"{F}/memory_working_set.csv", "w") as f:
    f.write("run,minutes,working_set_gib,desktops\n")
    for r, lab in RUNS:
        ev = [json.loads(l) for l in open(f"traces/{r}/events.jsonl")]
        t0 = ev[0]["t"]
        for l in open(f"traces/{r}/mem.jsonl"):
            m = json.loads(l)
            f.write(f"{lab},{(m['t'] - t0) / 60:.3f},{m['total'].get('cg_ws_mib', 0) / 1024:.3f},{len(m['containers'])}\n")
with open(f"{F}/rollout_finish_times.csv", "w") as f:
    f.write("run,task,k,finish_min,steps,reward,error,excluded_from_batch_plot\n")
    for r, lab in RUNS:
        ev = [json.loads(l) for l in open(f"traces/{r}/events.jsonl")]
        t0 = ev[0]["t"]
        for e in sorted((e for e in ev if e["event"] == "rollout_done"), key=lambda e: e["t"]):
            ex = e["task"].startswith("7a4e4bc8") and e["k"] == 0
            f.write(f"{lab},{e['task']},{e['k']},{(e['t'] - t0) / 60:.3f},{e['steps']},{e['reward']},{bool(e.get('error'))},{ex}\n")
print("ok")
