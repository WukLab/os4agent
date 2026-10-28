import json, os, collections
T = "/mnt/ssd2/vikranth/osworld/traces/rec32v2_tfork"; b = json.load(open("/mnt/ssd2/vikranth/osworld/grpo_batch32v2.json"))
ev = [json.loads(l) for l in open(f"{T}/events.jsonl")]; c = collections.Counter(e["event"] for e in ev)
print({k: c[k] for k in ("fork", "group_done", "group_error", "rollout_done")}, "clone failures:", sum(1 for e in ev if e["event"] == "tfork_clone" and not e["ok"]))
for e in ev:
    if e["event"] == "group_error": print("group_error", e["task"][:8], e["error"][:200])
full, part = 0, []
for dom, ids in b.items():
    for t in ids:
        n = [os.path.exists(f"{T}/{dom}/{t}__g{k}/chat.jsonl") for k in range(8)]
        errs = [json.load(open(f"{T}/{dom}/{t}__g{k}/timing.json")).get("error") for k in range(8) if os.path.exists(f"{T}/{dom}/{t}__g{k}/timing.json")]
        if all(n) and not any(errs): full += 1
        else: part.append((dom, t[:8], sum(n), [str(x)[:80] for x in errs if x][:2]))
print("fully recorded groups:", full, "/ 32"); [print("  incomplete:", p) for p in part]
rs = [float(open(os.path.join(r, "result.txt")).read()) for r in [f"{T}/{d}/{t}__g{k}" for d, ids in b.items() for t in ids for k in range(8)] if os.path.exists(r + "/result.txt")]
print(f"mean reward {sum(rs)/len(rs):.3f} over {len(rs)} rollouts, successes {sum(r > 0 for r in rs)}")
