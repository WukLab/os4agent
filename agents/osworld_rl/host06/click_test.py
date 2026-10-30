"""Click an element at its tree centre (as the agent does) on a running desktop and report what happens.
Usage: click_test.py <container> <ip> <file-on-desktop> <role> <name> <after-check-substring>"""
import json, re, subprocess, sys, time, urllib.request
C, ip, path, role, name, check = sys.argv[1:7]
P = ["env", "PODMAN_TFORK_SKIP_SYSCTL=1", "CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf",
     "CONTAINERS_CONF=/mnt/ssd2/vikranth/osworld/containers-os4agent.conf", "/mnt/ssd2/os4agent/podman-tfork.sh"]
def post(ep, d): return urllib.request.urlopen(urllib.request.Request(f"http://{ip}:5000{ep}", json.dumps(d).encode(), {"Content-Type": "application/json"}), timeout=120).read()
def tree():
    post("/execute", {"command": "xdotool mousemove_relative 1 0 sleep 0.2 mousemove_relative -- -1 0", "shell": True})
    return json.load(urllib.request.urlopen(f"http://{ip}:5000/accessibility", timeout=120))["AT"]
post("/setup/open_file", {"path": path}); time.sleep(12)
t = tree()
m = [x for x in re.finditer(rf'<{role} name="{re.escape(name)}"[^>]*?screencoord="\((\d+), (\d+)\)"[^>]*?size="\((\d+), (\d+)\)"', t)]
print(f"{role} {name!r}: {len(m)} match(es)", [(x[1], x[2], x[3], x[4]) for x in m][:3])
x, y = int(m[0][1]) + int(m[0][3]) // 2, int(m[0][2]) + int(m[0][4]) // 2
before = len(re.findall(check, t))
post("/execute", {"command": ["python", "-c", f"import pyautogui; pyautogui.moveTo({x}, {y}, duration=0.15); import time; time.sleep(0.1); pyautogui.click()"]}); time.sleep(2)
t2 = tree()
print(f"clicked ({x},{y}); '{check}' count before {before}, after {len(re.findall(check, t2))}")
print("dialogs/windows after:", sorted(set(re.findall(r'<(?:dialog|frame) name="([^"]*)"', t2)))[:8])
open(f"/tmp/vk_click_{role}.png", "wb").write(urllib.request.urlopen(f"http://{ip}:5000/screenshot", timeout=30).read())
