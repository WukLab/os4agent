"""Follow a run's events.jsonl and print one line per failure: failed clone (with reason), rollout/group error,
Traceback in the log; plus a progress line every 50 spec steps; exits at run_done."""
import json, os, sys, time
d = sys.argv[1]
ev_path, log_path = f"{d}/events.jsonl", f"{d}.log"
while not os.path.exists(ev_path):
    time.sleep(2)
f, lg = open(ev_path), open(log_path) if os.path.exists(log_path) else None
t0, spec, hits, fails = None, 0, 0, 0
while True:
    line = f.readline()
    if not line:
        if lg:
            for l in lg.readlines():
                if "Traceback" in l:
                    print("TRACEBACK in log", flush=True)
        time.sleep(1)
        continue
    e = json.loads(line)
    t0 = t0 or e["t"]
    m = f"{(e['t'] - t0) / 60:4.1f} min"
    k = e.get("event")
    if k in ("tfork_clone", "ckpt_clone") and not e.get("ok", True):
        fails += 1
        w = " ".join(e["why"]) if isinstance(e.get("why"), list) else str(e.get("why"))
        kind = "CASCADE resolve-parent" if "resolve parent" in w else "criu"
        print(f"{m} FAILED clone #{fails} [{kind}] {e.get('task', '')[:8]}: {w[-110:]!r}", flush=True)
    elif k == "rollout_done" and e.get("error"):
        print(f"{m} ROLLOUT ERROR {e['task'][:8]} k{e['k']}: {str(e['error'])[-150:]}", flush=True)
    elif k == "group_error":
        print(f"{m} GROUP ERROR {e['task'][:8]}: {str(e.get('error'))[-150:]}", flush=True)
    elif k == "spec_exec":
        spec += 1
        hits += e["hit"] is not None
        if e.get("waited_s", 0) > 1e9:  # long waits are slowness, not failures
            print(f"{m} long wait {e['waited_s']} s on {'hit' if e['hit'] is not None else 'miss'} {e['task'][:8]}", flush=True)
        if spec % 100 == 0:
            print(f"{m} progress: {spec} spec steps, {hits} hits, {fails} failed clones", flush=True)
    elif k == "run_done":
        print(f"{m} RUN DONE: {spec} spec steps, {hits} hits, {fails} failed clones", flush=True)
        break
