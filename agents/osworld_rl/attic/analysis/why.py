import json
for l in open("/mnt/ssd2/vikranth/osworld/traces/replay31_tfork/events.jsonl"):
    e = json.loads(l)
    if e["event"] == "tfork_clone" and e["attempt"] == 1:
        print(e["task"][:8]); [print("   ", w[:220]) for w in dict.fromkeys(e["why"])]; break
