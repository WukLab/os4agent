import json, statistics as st
T = "/mnt/ssd2/vikranth/osworld/traces"
def ev(r): return [json.loads(l) for l in open(f"{T}/{r}/events.jsonl")]
N = ev("aenv_nested4")
for e in N:
    if e["event"] in ("boot", "base_fork", "aenv_fork", "setup", "fork", "group_done", "group_error"):
        x = {k: e[k] for k in ("secs", "pair_secs", "copies", "error") if k in e}; t = e.get("total") or {}
        print(f"{e['event']:11s} {str(e.get('task', ''))[:8]:9s} {x}" + (f"  PSS {t['pss_mib']/1024:.2f} GiB" if t else ""))
def per(evs):
    g = {}
    for e in evs:
        if e["event"] in ("mem_before_fork", "fork", "group_done"): g.setdefault(e["task"], {})[e["event"]] = e["total"]
    return g
A, B = per(N), per(ev("replay32_aenv"))
ts = [t for t in A if t in B]
print(f"\nper group GiB, same {len(ts)} tasks      nested(base-fork)   regular AENV")
for k, name in (("mem_before_fork", "source after setup"), ("fork", "right after fork"), ("group_done", "after rollouts")):
    print(f"  {name:28s}{st.mean(A[t][k]['pss_mib'] for t in ts)/1024:12.2f}{st.mean(B[t][k]['pss_mib'] for t in ts)/1024:15.2f}")
bf = [e for e in N if e["event"] == "base_fork"]
if bf: print(f"  base VM + 4 task sources right after the base fork: PSS {bf[0]['total']['pss_mib']/1024:.2f} GiB")
