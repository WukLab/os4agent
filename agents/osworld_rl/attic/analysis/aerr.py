import json, glob, collections, statistics as st
R = "/mnt/ssd2/vikranth/osworld/traces"
for sysn in ("tfork", "criu", "aenv"):
    rows = []
    for d in glob.glob(f"{R}/replay31_{sysn}/*/*__g*"):
        tm = json.load(open(d + "/timing.json")); want = sum(1 for _ in open(d.replace(f"replay31_{sysn}", "osw_criu32_capped") + "/chat.jsonl"))
        rows.append((d.split("/")[-2], tm["steps"], want, tm.get("error"), tm["t_end"] - tm["t_start"]))
    done = sum(r[1] for r in rows); want = sum(r[2] for r in rows)
    print(f"{sysn}: steps executed {done}/{want} ({100*done/want:.0f}%), median rollout {st.median(r[4] for r in rows):.0f}s, errors {sum(1 for r in rows if r[3])}")
    if sysn == "aenv":
        print("  errors by domain:", collections.Counter(r[0] for r in rows if r[3]))
        print("  failing step (steps done before error):", sorted(collections.Counter(r[1] for r in rows if r[3]).items()))
