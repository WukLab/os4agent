import json, glob, os
r = "traces/spec_tail_B8c"
ev = [json.loads(l) for l in open(f"{r}/events.jsonl")]
t0 = ev[0]["t"]
done = {(e["task"][:8], e["k"]) for e in ev if e.get("event") == "rollout_done"}
for d in sorted(glob.glob(f"{r}/*/*__g*")):
    t, k = os.path.basename(d).split("__g")
    if (t[:8], int(k)) in done:
        continue
    traj = [json.loads(l) for l in open(f"{d}/traj.jsonl")] if os.path.exists(f"{d}/traj.jsonl") else []
    last = traj[-1] if traj else {}
    print(f"missing {t[:8]} k{k}: {len(traj)} steps, last step {last.get('step_num')} ({last.get('skipped', 'real')}, {last.get('exec_s')} s), "
          f"timing.json: {os.path.exists(f'{d}/timing.json')}, result: {open(f'{d}/result.txt').read().strip() if os.path.exists(f'{d}/result.txt') else '-'}")
for e in ev:
    if e.get("event") in ("group_done", "group_error", "run_done", "mem_limit"):
        print(f"{(e['t'] - t0) / 60:5.1f} min {e['event']} {e.get('task', '')[:8]} {str(e.get('error', e.get('rewards', '')))[:120]}")
