import json, sys
O = "/mnt/ssd2/vikranth/osworld/traces/osw_criu32_capped/chrome/7b6c7e24-c58a-49fc-a5bb-d57b80e5b4c3__g0/chat.jsonl"
R = "/mnt/ssd2/vikranth/osworld/traces/replay3_tfork/chrome/7b6c7e24-c58a-49fc-a5bb-d57b80e5b4c3__g0/chat.jsonl"
o = [json.loads(l) for l in open(O)]; r = [json.loads(l) for l in open(R)]
print("TASK:", o[0]["messages"][1]["content"].split("\n")[0][:300])
for i, (x, y) in enumerate(zip(o, r)):
    a = x["action"]; t = a.get("id", a.get("from"))
    tgt = x["rows"][t][:2] if isinstance(t, int) and t < len(x["rows"]) else None
    print(f"\nstep {i+1}: {json.dumps(a)[:90]} target={tgt}  replay={y['replay']} code={y['code'][:60]!r}")
    if i < 2:
        names = lambda rows: [f"{q[0]}|{q[1][:40]}" for q in rows]
        so, sr = names(x["rows"]), names(y["rows"])
        print("  rec rows:", len(so), " replay rows:", len(sr)); print("  only in rec:", [z for z in so if z not in sr][:12]); print("  only in replay:", [z for z in sr if z not in so][:12])
