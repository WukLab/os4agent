"""Sample every thread's scheduler state on the host, to see what blocked threads wait on. Run as root.

  sudo python3 thread_states.py OUT.jsonl [interval_s]

One line per sample: counts by state (R running, D uninterruptible, S sleeping) per command name, and for R and D
threads their kernel wait channel (/proc/<pid>/task/<tid>/wchan). Reads only stat and wchan, which do not take a
process's mmap lock (unlike smaps).
"""
import collections, json, os, sys, time

out, interval = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
with open(out, "a") as f:
    while True:
        t0 = time.time()
        states, waits = collections.Counter(), collections.Counter()
        for pid in filter(str.isdigit, os.listdir("/proc")):
            try:
                tids = os.listdir(f"/proc/{pid}/task")
            except OSError:
                continue
            for tid in tids:
                try:
                    stat = open(f"/proc/{pid}/task/{tid}/stat").read()
                    comm = stat[stat.index("(") + 1:stat.rindex(")")]
                    state = stat[stat.rindex(")") + 2]
                    states[f"{state} {comm}"] += 1
                    if state in "RD":
                        waits[f"{state} {comm} {open(f'/proc/{pid}/task/{tid}/wchan').read() or '-'}"] += 1
                except (OSError, ValueError):
                    pass
        load1 = os.getloadavg()[0]
        f.write(json.dumps({"t": t0, "load1": load1, "read_s": round(time.time() - t0, 2),
                            "states": dict(states.most_common(40)), "waits": dict(waits.most_common(40))}) + "\n")
        f.flush()
        time.sleep(max(0.0, interval - (time.time() - t0)))
