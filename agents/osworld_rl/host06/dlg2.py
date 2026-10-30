"""Open a doc, drive keys/clicks to a dialog, dump the agent-view rows of the dialog. Usage: dlg2.py <ip> <path> <steps json> <out>
steps: ["key:ctrl+h", "click:push-button:Format...", "sleep:3", ...]"""
import json, re, sys, time, urllib.request
sys.path.insert(0, "/mnt/ssd2/vikranth/osworld"); import a11y_owl_agent as A
ip, path, steps, out = sys.argv[1], sys.argv[2], json.loads(sys.argv[3]), sys.argv[4]
def post(ep, d): return urllib.request.urlopen(urllib.request.Request(f"http://{ip}:5000{ep}", json.dumps(d).encode(), {"Content-Type": "application/json"}), timeout=120).read()
def tree():
    post("/execute", {"command": "xdotool mousemove_relative 1 0 sleep 0.2 mousemove_relative -- -1 0", "shell": True})
    return json.load(urllib.request.urlopen(f"http://{ip}:5000/accessibility", timeout=180))["AT"]
post("/setup/open_file", {"path": path}); time.sleep(12)
for s in steps:
    kind, _, arg = s.partition(":")
    if kind == "sleep": time.sleep(float(arg)); continue
    if kind == "key": post("/execute", {"command": ["python", "-c", f"import pyautogui; pyautogui.hotkey(*{arg.split('+')!r})"]}); time.sleep(2); continue
    role, name = arg.split(":", 1)
    text, rows = A.linearize(tree())
    hit = [i for i, r in enumerate(rows) if r[0] == role and r[1] == name]
    print(s, "->", hit[:3])
    x, y, w, h = rows[hit[0]][2]
    post("/execute", {"command": ["python", "-c", f"import pyautogui; pyautogui.click({x + w // 2}, {y + h // 2})"]}); time.sleep(3)
raw = tree(); open(out + ".xml", "w").write(raw)
text, rows = A.linearize(raw)
open(out + ".txt", "w").write(text)
open(out + ".png", "wb").write(urllib.request.urlopen(f"http://{ip}:5000/screenshot", timeout=30).read())
print(len(rows), "rows")
