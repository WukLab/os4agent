import json, glob
p = glob.glob("traces/shot6_shot/libreoffice_calc/42e0a640*__g0/chat.jsonl")[0]
for i, l in enumerate(open(p)):
    x = json.loads(l)
    rows = x["rows"]
    dlg = [(j, r[0], r[1]) for j, r in enumerate(rows) if r[1] in ("OK", "Next Tip") or "Tip" in r[1]]
    li = sum(r[0] == "list-item" for r in rows)
    print(f"step {i + 1}: rows {len(rows)}, list-items {li}, dialog buttons in tree: {dlg[:4]}, action {x['action']}")
