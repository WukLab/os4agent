import json, sys, statistics as st
for run in sys.argv[1:]:
    ev = [json.loads(l) for l in open(f"/mnt/ssd2/vikranth/osworld/traces/{run}/events.jsonl")]
    g = lambda k, f: [e["total"][f] / 1024 for e in ev if e["event"] == k and "total" in e]
    pre, fk, dn = g("mem_before_fork", "pss_mib"), g("fork", "pss_mib"), g("group_done", "pss_mib")
    fa = g("fork", "pss_anon_mib")
    m = lambda x: f"{st.mean(x):.2f} (n={len(x)})" if x else "-"
    print(f"{run:22s} src={m(pre)}  fork={m(fk)}  fork_anon={m(fa)}  done={m(dn)}")
