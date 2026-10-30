# Call OSWorld's patched get_active_url_from_accessTree on a live desktop's tree. Usage: url_check.py <ip>
import sys, urllib.request, json
sys.path.insert(0, "/mnt/ssd2/vikranth/osworld/OSWorld")
from desktop_env.evaluators.getters.chrome import get_active_url_from_accessTree
ip = sys.argv[1]
class C:
    def get_accessibility_tree(self):
        return json.load(urllib.request.urlopen(f"http://{ip}:5000/accessibility", timeout=120))["AT"]
class E:
    controller, vm_machine = C(), "x86_64"
print("getter returned:", repr(get_active_url_from_accessTree(E(), {"goto_prefix": "https://"})))
