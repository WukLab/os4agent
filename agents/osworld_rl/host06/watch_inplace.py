"""Follow an in-place speculation run: outcome counts and waits at 1/10/50/100/... speculated steps, every failed
clone, rollout error and Traceback, and the run's end."""
import collections, json, os, statistics as st, sys, time
d = sys.argv[1]
while not os.path.exists(f"{d}/events.jsonl"):
    time.sleep(2)
f, lg = open(f"{d}/events.jsonl"), None
t0, sp, seen_tb = None, [], 0
marks = {1, 10, 50} | set(range(100, 5000, 100))
med = lambda v: f"{st.median(v):.1f}" if v else "-"
while True:
    line = f.readline()
    if not line:
        if lg is None and os.path.exists(f"{d}.log"):
            lg = open(f"{d}.log")
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
    if k == "tfork_clone" and not e.get("ok", True):
        w = " ".join(e["why"]) if isinstance(e.get("why"), list) else str(e.get("why"))
        print(f"{m} FAILED clone {e.get('task', '')[:8]}: {w[-120:]!r}", flush=True)
    elif k == "rollout_done" and e.get("error"):
        print(f"{m} ROLLOUT ERROR {e['task'][:8]} k{e['k']}: {str(e['error'])[-140:]}", flush=True)
    elif k == "spec_exec":
        sp.append(e)
        if e.get("error"):
            print(f"{m} spec {e.get('outcome')} with error: {e['error'][-140:]}", flush=True)
        if len(sp) in marks:
            c = collections.Counter(x.get("outcome") for x in sp)
            print(f"{m} {len(sp)} spec steps: {dict(c)}; fork {med([x['fork_s'] for x in sp if x['fork_s'] > 0])} s; "
                  f"wait hit {med([x['waited_s'] for x in sp if x.get('outcome') == 'hit'])} s, "
                  f"miss {med([x['waited_s'] for x in sp if x.get('outcome') == 'miss'])} s", flush=True)
    elif k == "run_done":
        c = collections.Counter(x.get("outcome") for x in sp)
        print(f"{m} RUN DONE: {len(sp)} spec steps {dict(c)}", flush=True)
        break
