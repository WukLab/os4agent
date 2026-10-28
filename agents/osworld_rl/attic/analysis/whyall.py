import json, collections, sys
ev = [json.loads(l) for l in open(f"/mnt/ssd2/vikranth/osworld/traces/{sys.argv[1]}/events.jsonl")]
cl = [e for e in ev if e["event"] == "tfork_clone"]
fail = [e for e in cl if not e["ok"]]
print(f"clone attempts {len(cl)}, failed {len(fail)}, groups needing a retry {len({e['task'] for e in fail})} of {len({e['task'] for e in cl})}")
print("attempts per group:", collections.Counter(collections.Counter(e["task"] for e in cl).values()))
reasons = collections.Counter()
for e in fail:
    w = e["why"] if isinstance(e["why"], list) else [e["why"]]
    for x in dict.fromkeys(w):
        x = x.split("see /mnt")[0].strip()
        if "Error" in x: reasons[x[-140:]] += 1
for r, n in reasons.most_common(8): print(f"{n:3d}  {r}")
# load at failure time: how many groups were forking or setting up then
for e in fail[:3]:
    print("fail", e["task"][:8], "attempt", e["attempt"], "secs", e["secs"])
