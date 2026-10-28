import json, os, collections
T = "/mnt/ssd2/vikranth/osworld/traces"
for run in ("replay31_tfork", "replay31_criu", "replay31_aenv_direct", "rec32v2_tfork", "replay32_tfork", "replay32_criu", "replay32_aenv"):
    p = f"{T}/{run}/events.jsonl"
    if not os.path.exists(p): continue
    ev = [json.loads(l) for l in open(p)]; c = collections.Counter(e["event"] for e in ev)
    if "tfork" in run:
        cl = [e for e in ev if e["event"] == "tfork_clone"]; bad = [e for e in cl if not e["ok"]]
        print(f"{run:22s} fork calls {len(cl):3d}  failed {len(bad):2d}  groups retried {len({e['task'] for e in bad})}/{c['fork']}")
    elif "criu" in run:
        ok = c["ckpt_clone"]; bad = [e for e in ev if e["event"] == "ckpt_clone_failed"]
        print(f"{run:22s} fork calls {ok + len(bad):3d}  failed {len(bad):2d}  groups retried {len({e['task'] for e in bad})}/{c['fork']}   (CKPT: 8 serial dump+restore per group)")
    else:
        f = [e for e in ev if e["event"] == "aenv_fork"]
        print(f"{run:22s} fork calls {len(f):3d}  failed {c['group_error']:2d}  (AENV fork API, no retry loop; failures would show as group_error)  groups={c['fork']}")
