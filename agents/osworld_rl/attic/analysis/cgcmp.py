import json, statistics as st
def load(r):
    g = {}
    for l in open(f"/mnt/ssd2/vikranth/osworld/traces/{r}/events.jsonl"):
        e = json.loads(l)
        if e["event"] in ("fork", "group_done"): g.setdefault(e["task"], {})[e["event"]] = e["total"]
    return g
A, B = load("replay32_tfork_overlay"), load("replay32_tfork")
ts = [t for t in A if t in B and all(k in A[t] and k in B[t] for k in ("fork", "group_done"))]
print(f"{'per group GiB (n=%d)' % len(ts):28s}{'overlay':>9s}{'snapshot':>9s}")
for ev in ("fork", "group_done"):
    for k in ("pss_mib", "pss_anon_mib", "pss_file_mib", "pss_shmem_mib", "cg_mib", "cg_anon_mib", "cg_file_mib", "cg_kernel_mib"):
        print(f"{ev+' '+k:28s}{st.mean(A[t][ev][k] for t in ts)/1024:9.2f}{st.mean(B[t][ev][k] for t in ts)/1024:9.2f}")
# overlap: how many groups were in rollouts at once over time
for r in ("replay32_tfork_overlay", "replay32_tfork"):
    rows = [json.loads(l) for l in open(f"/mnt/ssd2/vikranth/osworld/traces/{r}/mem.jsonl")]
    n = [sum(1 for v in x["phases"].values() if v == "rollouts") for x in rows]
    print(f"{r}: groups in rollouts at once  mean {st.mean(n):.1f}  max {max(n)}  share of time with 8: {sum(1 for v in n if v == 8)/len(n):.0%}")
