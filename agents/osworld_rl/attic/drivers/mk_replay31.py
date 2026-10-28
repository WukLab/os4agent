import json, glob, os
T = "/mnt/ssd2/vikranth/osworld/traces/osw_criu32_capped"; out = {}
for dom, ids in json.load(open("/mnt/ssd2/vikranth/osworld/grpo_batch32.json")).items():
    if dom in ("thunderbird", "vs_code", "os"): continue   # excluded from the comparison
    for t in ids:
        if all(os.path.exists(f"{T}/{dom}/{t}__g{k}/chat.jsonl") for k in range(8)): out.setdefault(dom, []).append(t)
json.dump(out, open("/mnt/ssd2/vikranth/osworld/replay31.json", "w"), indent=1)
print({k: len(v) for k, v in out.items()}, sum(map(len, out.values())))
