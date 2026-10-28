import json, os, glob
os.chdir("/mnt/ssd2/vikranth/osworld/traces")
rows = []
for d in sorted(glob.glob("*/config.json")):
    d = os.path.dirname(d); c = json.load(open(d + "/config.json"))
    ev = [json.loads(l) for l in open(d + "/events.jsonl")] if os.path.exists(d + "/events.jsonl") else []
    n = lambda k: sum(e["event"] == k for e in ev)
    rows.append((os.path.getmtime(d + "/config.json"), f"{d:28s} {c['system']:6s} {os.path.basename(c['tasks']):22s} R={c['rollouts']} steps={c['max_steps']} par={c.get('parallel')} memcopy={c.get('full_memcopy')} base={c.get('base_fork', 0)} forks={n('fork')} done={n('group_done')} err={n('group_error')}"))
for t, r in sorted(rows): print(r)
