"""python test_a11y_agent.py traces/<run>  (run from the osworld dir)   offline: real saved trees, oracle answers, no LLM."""
import glob, gzip, json, re, sys
sys.path.insert(0, "."); from a11y_owl_agent import linearize, to_code, parse
R = sys.argv[1]; n = ok = bad = 0; toks = []
for d in glob.glob(f"{R}/results/*/*/*/*/*__g*"):
    for l in open(f"{d}/traj.jsonl"):
        t = json.loads(l)
        h = t.get("a11y_hit") if "step_num" in t else None
        if not h or not h.get("key"): continue
        f = f"{d}/step_{t['step_num']}_{t['action_timestamp']}.a11y.xml.gz"
        try: text, rows = linearize(gzip.open(f, "rt").read())
        except Exception: continue
        toks.append(len(text) / 3.5); n += 1
        idx = [i for i, (r, nm, b) in enumerate(rows) if r == h["role"] and nm[:80] == h["name"][:80] and list(b) == h["bbox"]]
        if not idx: bad += 1; continue          # target cut by MAX_ROWS or name trimmed
        code = to_code(parse(f'Thought: x\nAction: {{"action":"click","id":{idx[0]}}}'), rows)
        x, y = map(int, re.findall(r"\((\d+), (\d+)\)", code)[0]); bx, by, bw, bh = h["bbox"]
        ok += bx <= x < bx + bw and by <= y < by + bh
print(f"oracle clicks: {n}; target still in capped list: {n-bad}; click lands inside target bbox: {ok}/{n-bad}")
toks.sort(); print(f"prompt text tokens (est) p50 {toks[len(toks)//2]:.0f} p90 {toks[int(len(toks)*.9)]:.0f} max {toks[-1]:.0f}")
rows = [("push-button", "OK", (10, 20, 30, 40)), ("entry", "Search", (100, 200, 50, 20))]
for r, want in [('Action: {"action":"type","text":"it\'s\\n"}', "press('enter')"), ('Thought: hi\nAction: {"action":"key","keys":["ctrl","s"]}', "hotkey('ctrl', 's')"),
                ('Action: {"action":"scroll","id":1,"direction":"down"}', "scroll(-5"), ('Action: {"action":"drag","from":0,"to":1}', "dragTo(125, 210"),
                ('Action: {"action":"done"}', "DONE"), ('Action: {"action":"click","id":0}', "click(25, 40)")]:
    c = to_code(parse(r), rows); assert want in c, (r, c)
for bad_r in ('no action here', 'Action: {"action":"click","id":9}', 'Action: {"action":"zoom"}'):
    try: to_code(parse(bad_r), rows); raise SystemExit("should have failed: " + bad_r)
    except (ValueError, IndexError, json.JSONDecodeError, KeyError): pass
assert parse('Action: {"action":"click","id":[3]} \n Action: {"action":"click","id":4}')["id"] == 3 and parse('Action: {"action":"click","id":"7"}')["id"] == 7
print("parse/to_code unit checks passed")
# two maximised Chrome windows (only the active one is on screen) + a popup bubble that is never active but sits on top
B = lambda n, x, y, w, h, extra="": f'<push-button name="{n}" showing="true" screencoord="({x}, {y})" size="({w}, {h})" {extra}/>'
W = lambda tag, n, act, kids: f'<{tag} name="{n}" showing="true" screencoord="(70, 27)" size="(1850, 1053)" {act}>{kids}</{tag}>'
xml = ('<desktop-frame><application name="Google Chrome">' + W("frame", "old", "", B("Stale", 100, 100, 50, 20)) + W("frame", "new", 'active="true"', B("Live", 100, 100, 50, 20))
       + '<alert name="Bubble" showing="true" screencoord="(1500, 100)" size="(300, 200)">' + B("Popup", 1600, 150, 50, 20) + '</alert></application>'
       + '<application name="gnome-shell"><window name="" showing="true" screencoord="(0, 0)" size="(1920, 1080)">' + B("Dock", 5, 500, 60, 60) + '</window></application></desktop-frame>')
names = [n for _, n, _ in linearize(xml)[1]]
assert "Stale" not in names and {"new", "Live", "Bubble", "Popup", "Dock"} <= set(names), names
assert "Stale" in [n for _, n, _ in linearize(xml.replace('active="true"', ""))[1]]   # no active window -> keep everything
print("occlusion check passed")
