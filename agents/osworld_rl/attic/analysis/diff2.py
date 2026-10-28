import json, sys
t = "libreoffice_calc/26a8440e-c166-4c50-aef4-bfb77314b46b__g0"
O = f"/mnt/ssd2/vikranth/osworld/traces/osw_criu32_capped/{t}/chat.jsonl"
o = [json.loads(l) for l in open(O)]
for run in ("replay3_tfork", "replay3_aenv_direct"):
    r = [json.loads(l) for l in open(f"/mnt/ssd2/vikranth/osworld/traces/{run}/{t}/chat.jsonl")]
    print(f"== {run}: per-step resolution", [x["replay"][0] for x in r])
    for i in range(len(r)):
        if r[i]["replay"] != "coords": continue
        a = o[i]["action"]; k = a.get("id", a.get("from")); tgt = o[i]["rows"][k][:2]
        names = {f"{q[0]}|{q[1]}" for q in r[i]["rows"]}
        near = [n for n in names if tgt[1][:12].lower() in n.lower()][:4]
        print(f"   step {i+1}: wanted {tgt}; rows now={len(r[i]['rows'])}; similar names now: {near}")
        if i > 6: break
