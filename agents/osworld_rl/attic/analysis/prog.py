import json, collections, os, time
for r in ("replay32_tfork", "replay32_criu", "replay32_aenv"):
    p = f"/mnt/ssd2/vikranth/osworld/traces/{r}/events.jsonl"
    if not os.path.exists(p): continue
    ev = [json.loads(l) for l in open(p)]; c = collections.Counter(e["event"] for e in ev)
    fails = [e for e in ev if e["event"] in ("tfork_clone", "ckpt_clone_failed") and not e.get("ok", False)]
    rerr = [e for e in ev if e["event"] == "rollout_done" and e.get("error")]
    print(f"{r}: forks={c['fork']} groups_done={c['group_done']} group_err={c['group_error']} rollouts={c['rollout_done']} rollout_err={len(rerr)} "
          f"clone_failures={len(fails)} last_event={time.strftime('%H:%M', time.localtime(ev[-1]['t']))}")
    for e in [e for e in ev if e["event"] == "group_error"][:3]: print("   group_error", e["task"][:8], e["error"][:160])
    for e in rerr[:3]: print("   rollout_err", e["task"][:8], str(e["error"])[:160])
