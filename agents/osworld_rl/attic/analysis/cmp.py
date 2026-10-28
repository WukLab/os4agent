import json, glob, os, sys
R, O = sys.argv[1], "/mnt/ssd2/vikranth/osworld/traces/osw_criu32_capped"
ev = [json.loads(l) for l in open(f"{R}/events.jsonl")]
for e in ev:
    if e["event"] in ("fork", "group_error", "group_done"): print(e["event"], e.get("task", "")[:8], e.get("secs", ""), e.get("error", ""), e.get("rewards", ""))
tot = {"match": 0, "coords": 0, "no_target": 0}
for d in sorted(glob.glob(f"{R}/*/*__g*")):
    rel = os.path.relpath(d, R); tm = json.load(open(d + "/timing.json"))
    for k, v in (tm.get("replay") or {}).items(): tot[k] += v
    o = float(open(f"{O}/{rel}/result.txt").read()); n = float(open(d + "/result.txt").read())
    os_ = sum(1 for _ in open(f"{O}/{rel}/chat.jsonl"))
    print(f"{rel[:40]:40s} orig={o} replay={n} steps {os_}->{tm['steps']} {tm.get('replay')} err={tm.get('error')}")
print("TOTAL", tot)
