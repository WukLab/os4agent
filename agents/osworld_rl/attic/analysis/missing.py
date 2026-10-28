import json, os
T = "/mnt/ssd2/vikranth/osworld/traces/osw_criu32_capped"
b = json.load(open("/mnt/ssd2/vikranth/osworld/grpo_batch32.json"))
print("batch32:", {k: len(v) for k, v in b.items()}, sum(map(len, b.values())))
for dom, ids in b.items():
    for t in ids:
        n = sum(os.path.exists(f"{T}/{dom}/{t}__g{k}/chat.jsonl") for k in range(8))
        if n < 8: print("not fully recorded:", dom, t, f"{n}/8 rollouts")
ev = [json.loads(l) for l in open(f"{T}/events.jsonl")]
for e in ev:
    if e["event"] == "group_error": print("recording group_error:", e["task"][:8], e["error"][:150])
