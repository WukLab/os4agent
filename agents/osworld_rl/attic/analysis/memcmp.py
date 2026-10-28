import json, glob, statistics as st
R = "/mnt/ssd2/vikranth/osworld/traces"; S = ("tfork", "criu", "aenv_direct")
def per_group(sysn):
    out = {}
    for l in open(f"{R}/replay31_{sysn}/events.jsonl"):
        e = json.loads(l)
        if e["event"] in ("mem_before_fork", "fork", "group_done"):
            out.setdefault(e["task"], {})[e["event"]] = (e["total"]["pss_mib"] / 1024, e["total"]["pss_anon_mib"] / 1024)
    return out
G = {s: per_group(s) for s in S}
ok = set()   # groups where every AENV rollout ran all its recorded steps
for t in G["aenv_direct"]:
    ds = glob.glob(f"{R}/replay31_aenv_direct/*/{t}__g*")
    if ds and all(not json.load(open(d + "/timing.json")).get("error") for d in ds): ok.add(t)
def table(tasks, title):
    print(f"\n{title} (n={len(tasks)} groups)")
    print(f"{'GiB per group':34s}" + "".join(f"{s:>9s}" for s in S))
    for ev, idx, name in (("mem_before_fork", 0, "source PSS (after setup)"), ("fork", 0, "PSS right after fork"), ("fork", 1, "  anon right after fork"),
                          ("group_done", 0, "PSS after rollouts"), ("group_done", 1, "  anon after rollouts")):
        print(f"{name:34s}" + "".join(f"{st.mean(G[s][t][ev][idx] for t in tasks):9.2f}" for s in S))
common = [t for t in G["tfork"] if all(t in G[s] and all(k in G[s][t] for k in ("mem_before_fork", "fork", "group_done")) for s in S)]
table(common, "All groups (AENV after-rollout rows understated: 2/184 AENV rollouts died early)")
table([t for t in common if t in ok], "Groups where all 8 AENV rollouts completed")
for s in S:
    rows = [json.loads(l) for l in open(f"{R}/replay31_{s}/mem.jsonl")]
    print(f"{s}: peak total PSS {max(r['total']['pss_mib'] for r in rows)/1024:.1f} GiB, peak host used delta {max(r['host']['used_delta_mib'] for r in rows)/1024:.1f} GiB, run {(rows[-1]['t']-rows[0]['t'])/60:.0f} min")
