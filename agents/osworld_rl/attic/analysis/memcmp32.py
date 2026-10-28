import json, glob, statistics as st
R = "/mnt/ssd2/vikranth/osworld/traces"
RUNS = {"tf_ovl": ["replay32_tfork_overlay"], "tfork": ["replay32_tfork"], "criu": ["replay32_criu"], "aenv": ["replay32_aenv", "replay32_aenv_rerun1"]}
def load(runs):
    g, err = {}, {}
    for run in runs:
        for l in open(f"{R}/{run}/events.jsonl"):
            e = json.loads(l)
            if e["event"] in ("mem_before_fork", "fork", "group_done"):
                g.setdefault(e["task"], {})[e["event"]] = (e["total"]["pss_mib"] / 1024, e["total"]["pss_anon_mib"] / 1024, e["total"]["pss_file_mib"] / 1024)
        for d in glob.glob(f"{R}/{run}/*/*__g*"):
            t = d.split("/")[-1].split("__g")[0]; tm = json.load(open(d + "/timing.json"))
            err.setdefault(t, []).append(tm.get("error"))
    return g, err
G, E = {}, {}
for s, runs in RUNS.items(): G[s], E[s] = load(runs)
common = [t for t in G["tf_ovl"] if all(all(k in G[s].get(t, {}) for k in ("mem_before_fork", "fork", "group_done")) for s in RUNS)]
for s in RUNS:
    n = sum(len(v) for v in E[s].values()); bad = sum(1 for v in E[s].values() for x in v if x)
    print(f"{s}: groups with full data {sum(1 for t in G[s] if 'group_done' in G[s][t])}, rollouts {n}, rollout errors {bad}")
def table(tasks, title):
    print(f"\n{title} (n={len(tasks)})"); print(f"{'GiB per group':30s}" + "".join(f"{s:>8s}" for s in RUNS))
    for ev, i, name in (("mem_before_fork", 0, "source after setup"), ("fork", 0, "right after fork"), ("fork", 1, "  anon"), ("group_done", 0, "after rollouts"), ("group_done", 1, "  anon"), ("fork", 2, "  file (page cache)"), ("group_done", 2, "  file after rollouts")):
        print(f"{name:30s}" + "".join(f"{st.mean(G[s][t][ev][i] for t in tasks):8.2f}" for s in RUNS))
table(common, "All 32 groups")
table([t for t in common if not any(any(E[s].get(t, [])) for s in RUNS)], "Groups with no failed rollout on any system")
for s, runs in RUNS.items():
    rows = [json.loads(l) for l in open(f"{R}/{runs[0]}/mem.jsonl")]
    print(f"{s:6s} ({runs[0]}): peak PSS {max(r['total']['pss_mib'] for r in rows)/1024:.1f} GiB, peak host used {max(r['host']['used_delta_mib'] for r in rows)/1024:.1f} GiB, {(rows[-1]['t']-rows[0]['t'])/60:.0f} min")
