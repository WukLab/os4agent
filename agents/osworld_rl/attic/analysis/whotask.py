import json, glob, os, collections
dom = {}
for f in ("grpo_batch32v2.json", "grpo_batch32.json"):
    for d, ids in json.load(open(f"/mnt/ssd2/vikranth/osworld/{f}")).items():
        for t in ids: dom[t] = d
for run in ("replay31_tfork", "rec32v2_tfork", "replay32_tfork"):
    ev = [json.loads(l) for l in open(f"/mnt/ssd2/vikranth/osworld/traces/{run}/events.jsonl")]
    cl = [e for e in ev if e["event"] == "tfork_clone"]; bad = collections.Counter(e["task"] for e in cl if not e["ok"])
    t0 = ev[0]["t"]
    print(f"{run}: {len(bad)}/{len({e['task'] for e in cl})} groups retried:",
          ", ".join(f"{dom.get(t,'?')}:{t[:8]}x{n}@{(min(e['t'] for e in cl if e['task']==t)-t0)/60:.0f}min" for t, n in bad.most_common()))
