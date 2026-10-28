"""1 Hz host sampler: python host_sampler.py <out.jsonl>.  CPU split (user/sys/iowait/idle), load, mem, disk io, net, #qemu procs."""
import json, os, sys, time
def cpu():
    v = list(map(int, open("/proc/stat").readline().split()[1:])); return v[0] + v[1], v[2], v[4], sum(v)  # user+nice, sys, iowait, total
def mem():
    m = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}; return m["MemAvailable"] / 2**20, m["MemTotal"] / 2**20
def io():
    r = w = 0
    for l in open("/proc/diskstats"):
        f = l.split()
        if f[2] in ("sda", "sdb"): r += int(f[5]); w += int(f[9])
    return r * 512, w * 512
prev, pio = cpu(), io()
with open(sys.argv[1], "a") as o:
    while True:
        time.sleep(1); c, i = cpu(), io(); d = [a - b for a, b in zip(c, prev)]; t = d[3] or 1
        q = sum(1 for p in os.listdir("/proc") if p.isdigit() and open(f"/proc/{p}/comm").read().startswith("qemu")) if False else None
        o.write(json.dumps({"t": time.time(), "user": d[0] / t, "sys": d[1] / t, "iowait": d[2] / t, "load1": os.getloadavg()[0],
                            "mem_avail_gb": mem()[0], "disk_r_MBps": (i[0] - pio[0]) / 2**20, "disk_w_MBps": (i[1] - pio[1]) / 2**20}) + "\n"); o.flush()
        prev, pio = c, i
