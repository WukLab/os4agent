import json, os, subprocess, sys, time, urllib.request, logging
OSW = "/mnt/ssd2/vikranth/osworld/OSWorld"
sys.path.insert(0, OSW)
logging.basicConfig(level=logging.WARNING)
from desktop_env import desktop_env as dem
from desktop_env.desktop_env import DesktopEnv
from desktop_env.evaluators import metrics
C = os.environ.get("ORACLE_C", "oracle-lo")
P = ["sudo", "env", "PODMAN_TFORK_SKIP_SYSCTL=1", "CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf",
     "CONTAINERS_CONF=/mnt/ssd2/vikranth/osworld/containers-os4agent.conf", "/mnt/ssd2/os4agent/podman-tfork.sh"]
HF = "https://huggingface.co/datasets/xlangai/ubuntu_osworld_file_cache/resolve/main/"
D = "/mnt/ssd2/vikranth/osworld/oracle_dl/"
ip = sys.argv[1]
addr = f"{ip}:5000:9222:8006:8080"

class FP:
    def start_emulator(self,*a,**k): pass
    def get_ip_address(self,*a,**k): return addr
    def stop_emulator(self,*a,**k): pass
    def revert_to_snapshot(self,*a,**k): raise RuntimeError
    def save_state(self,*a,**k): pass
class FM:
    def get_vm_path(self,*a,**k): return "external"
dem.create_vm_manager_and_provider = lambda *a, **k: (FM(), FP())

def ex(cmd):
    return subprocess.run(P + ["exec", C, "bash", "-c", cmd], capture_output=True, text=True).stdout.strip()

def fetch(url, dest):
    if not os.path.exists(dest):
        urllib.request.urlretrieve(url, dest)
    return dest

TASKS = {  # task -> oracle file (local)
 "libreoffice_calc/42e0a640-4f19-4b28-973d-729602b5a4a7": HF+"libreoffice_calc/42e0a640-4f19-4b28-973d-729602b5a4a7/2_NetIncome_gt1.xlsx",
 "libreoffice_calc/357ef137-7eeb-4c80-a3bb-0951f26a8aff": D+"357_oracle.xlsx",
 "libreoffice_calc/26a8440e-c166-4c50-aef4-bfb77314b46b": HF+"libreoffice_calc/26a8440e-c166-4c50-aef4-bfb77314b46b/3_SalesRep_gt1.xlsx",
 "libreoffice_calc/7a4e4bc8-922c-4c84-865c-25ba34136be1": HF+"libreoffice_calc/7a4e4bc8-922c-4c84-865c-25ba34136be1/Name_Order_Id_move_column_gold.xlsx",
 "libreoffice_calc/6e99a1ad-07d2-4b66-a1ce-ece6d99c20a5": HF+"libreoffice_calc/6e99a1ad-07d2-4b66-a1ce-ece6d99c20a5/Keep_Two_decimal_points_gold.xlsx",
 "libreoffice_calc/4e6fcf72-daf3-439f-a232-c434ce416af6": HF+"libreoffice_calc/4e6fcf72-daf3-439f-a232-c434ce416af6/Employee_Age_By_Birthday_gold.xlsx",
 "libreoffice_writer/0810415c-bde4-4443-9047-d5f70165a697": HF+"libreoffice_writer/0810415c-bde4-4443-9047-d5f70165a697/Novels_Intro_Packet_Gold.docx",
 "libreoffice_impress/7dbc52a6-11e0-4c9a-a2cb-1e36cfda80d8": HF+"libreoffice_impress/7dbc52a6-11e0-4c9a-a2cb-1e36cfda80d8/164_3_Gold.pptx",
 "libreoffice_impress/5d901039-a89c-4bfb-967b-bf66f4df075e": D+"5d9_oracle.pptx",
}
if os.environ.get("ORACLE_TASKS"): TASKS = json.load(open(os.environ["ORACLE_TASKS"]))  # {app/id: gold url}
mode = sys.argv[2] if len(sys.argv) > 2 else "swap"   # swap: doc shows gold, disk holds original -> score needs Ctrl+S to save
only = sys.argv[3:] 
for t, g in TASKS.items():
    if only and not any(o in t for o in only): continue
    if g.startswith("http"): g = fetch(g, D + t.split("/")[1][:8] + "_" + g.rsplit("/", 1)[1])
    task = json.load(open(f"{OSW}/evaluation_examples/examples/{t}.json"))
    path = task["config"][1]["parameters"]["path"]
    ex("pkill -9 -f soffice; rm -f /config/.~lock* /config/Desktop/.~lock*; rm -f /config/*.xlsx /config/*.csv /config/Desktop/*"); time.sleep(2)
    env = DesktopEnv(provider_name="docker", path_to_vm=f"external-{addr}", action_space="pyautogui",
                     require_a11y_tree=False, headless=True, recording_update="off")
    env.reset(task_config=task)
    time.sleep(12)
    ex(f"cp {path} /tmp/orig; pkill -9 -f soffice; rm -f $(dirname {path})/.~lock*"); time.sleep(2)
    subprocess.run(P + ["cp", g, f"{C}:{path}"], capture_output=True); ex(f"chown abc:abc {path}")
    env.setup_controller.setup([{"type": "open", "parameters": {"path": path}}])
    time.sleep(12)
    if mode == "swap":  # disk back to original content, same mtime LO recorded
        ex(f"M=$(stat -c %y {path}); cp /tmp/orig {path}; touch -d \"$M\" {path}")
    m0 = ex(f"stat -c %Y {path}; md5sum < {path}")
    wins = ex("DISPLAY=:1 wmctrl -l | cut -c 15-")
    try:
        s = env.evaluate()
    except Exception as e:
        s = f"ERR {e!r}"
    m1 = ex(f"stat -c %Y {path}; md5sum < {path}")
    wins2 = ex("DISPLAY=:1 wmctrl -l | cut -c 15-")
    print(json.dumps({"task": t, "score": s, "saved": m0 != m1, "wins_before": wins, "wins_after": wins2}), flush=True)
    open(f"/tmp/oracle/{t.split('/')[1][:8]}_{mode}.png", "wb").write(env.controller.get_screenshot() or b"")
    env.close() if hasattr(env, "close") and False else None
