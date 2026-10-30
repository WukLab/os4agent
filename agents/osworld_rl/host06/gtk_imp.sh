#!/bin/bash
# In imp-test: Impress notes with backend $1 (gtk3|qt5). View > Notes, click the notes placeholder, type, and print
# the notes paragraph(s) from the tree while editing and after Escape.
cd /mnt/ssd2/vikranth/osworld
P="env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
$P exec imp-test pkill -f soffice; sleep 2
$P cp /tmp/vk_w/164_3.pptx imp-test:/config/164_3.pptx; $P exec imp-test chown abc:abc /config/164_3.pptx
$P exec imp-test bash -c "setsid nohup setpriv --reuid=abc --regid=abc --init-groups -- env HOME=/config DISPLAY=:1 XDG_RUNTIME_DIR=/config/.XDG SAL_USE_VCLPLUGIN=$1 QT_ACCESSIBILITY=1 NO_AT_BRIDGE=0 soffice --impress /config/164_3.pptx >/tmp/lo.log 2>&1 < /dev/null &"
sleep 25
ip=$($P inspect -f "{{.NetworkSettings.IPAddress}}" imp-test)
X="$P exec imp-test env DISPLAY=:1 xdotool"
notes() { curl -s -m 90 http://$ip:5000/accessibility | python3 -c '
import json,sys,re
t=json.load(sys.stdin).get("AT") or ""
for m in re.finditer(r"<paragraph[^>]*?screencoord=\"\((\d+), (\d+)\)\"[^>]*?size=\"\((\d+), (\d+)\)\"[^>]*>([^<]*)", t):
    if "Notes" in m[5] or "XYZ" in m[5]: print("    paragraph", repr(m[5][:60]), "at", m[1], m[2])
m=re.search(r"<paragraph[^>]*?screencoord=\"\((\d+), (\d+)\)\"[^>]*?size=\"\((\d+), (\d+)\)\"[^>]*>Click to add Notes", t)
open("/tmp/vk_nc","w").write("%d %d" % (int(m[1])+int(m[3])//2, int(m[2])+int(m[4])//2) if m else "")'; }
$X key Escape; sleep 1; $X key alt+v; sleep 1; $X key e; sleep 4
echo "[$1] notes view:"; notes; c=$(cat /tmp/vk_nc); echo "  placeholder click at: $c"
[ -n "$c" ] && { $X mousemove $c click 1; sleep 1; $X type --delay 50 "XYZ Team Members"; sleep 3; }
echo "[$1] after typing (editing):"; notes
curl -s -m 30 http://$ip:5000/screenshot -o /tmp/vk_imp_$1.png
$X key Escape; sleep 1; $X key Escape; sleep 3
echo "[$1] after Escape:"; notes
