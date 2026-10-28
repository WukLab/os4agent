import json, glob, os
T = "/mnt/ssd2/vikranth/osworld/traces/osw_criu32_capped"
pick = {}
for dom in ("chrome", "libreoffice_calc", "gimp"):
    for t in sorted({os.path.basename(p).split("__g")[0] for p in glob.glob(f"{T}/{dom}/*__g*")}):
        g = [f"{T}/{dom}/{t}__g{k}" for k in range(8)]
        if all(os.path.exists(x + "/chat.jsonl") for x in g):
            steps = [sum(1 for _ in open(x + "/chat.jsonl")) for x in g]
            r = [float(open(x + "/result.txt").read()) for x in g]
            pick[dom] = [t]; print(dom, t, "steps", steps, "rewards", r); break
json.dump(pick, open("/mnt/ssd2/vikranth/osworld/replay3.json", "w"), indent=1)
