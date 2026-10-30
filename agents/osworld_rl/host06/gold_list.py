import json, glob, os
ids = {"libreoffice_calc": ["4188d3a4", "1273e544", "1954cced"], "libreoffice_writer": ["3ef2b351", "d53ff5ee", "e246f6d8"],
       "libreoffice_impress": ["73c99fb9", "39be0d19", "9ec204e4"]}
out = {}
for app, ps in ids.items():
    for p in ps:
        f = glob.glob(f"OSWorld/evaluation_examples/examples/{app}/{p}*.json")[0]
        t = json.load(open(f)); ev = t["evaluator"]
        exp = ev.get("expected"); exp = exp[0] if isinstance(exp, list) else exp
        ok = bool(exp) and exp.get("type") == "cloud_file" and t["config"][1]["type"] == "open"
        func = ev["func"] if isinstance(ev["func"], str) else ev["func"][0]
        print(f"{app[12:]:8} {p} func={func:28} expected={(exp or {}).get('type')} gold-swap-ok={ok}")
        if ok:
            out[app + "/" + os.path.basename(f)[:-5]] = exp["path"]
json.dump(out, open("oracle_new.json", "w"), indent=1)
print(len(out), "tasks with a gold file")
