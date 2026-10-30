#!/bin/bash
# Impress notes: does the a11y tree show text typed into the notes placeholder? Open 164_3.pptx, View > Notes,
# click "Click to add Notes", type, then dump the notes paragraph(s) from /accessibility + a screenshot.
cd /mnt/ssd2/vikranth/osworld
P="env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
$P rm -f imp-test >/dev/null 2>&1
$P run -d --name imp-test --cgroupns=host --security-opt seccomp=unconfined --security-opt label=disable --shm-size=2g \
  --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$(cat desk_osw.sh)" >/dev/null
sleep 35
$P cp /tmp/vk_w/164_3.pptx imp-test:/config/164_3.pptx; $P exec imp-test chown abc:abc /config/164_3.pptx
$P exec imp-test bash -c 'setsid nohup setpriv --reuid=abc --regid=abc --init-groups -- env HOME=/config DISPLAY=:1 QT_ACCESSIBILITY=1 soffice --impress /config/164_3.pptx >/dev/null 2>&1 < /dev/null &'
sleep 25
ip=$($P inspect -f "{{.NetworkSettings.IPAddress}}" imp-test)
X="$P exec imp-test env DISPLAY=:1 xdotool"
notes() { curl -s -m 60 http://$ip:5000/accessibility | python3 -c '
import json,sys,re
t=json.load(sys.stdin).get("AT") or ""
for m in re.finditer(r"<(paragraph|text)[^>]*name=\"([^\"]*)\"[^>]*>([^<]*)", t):
    if "Notes" in m.group(2) or "Team" in m.group(2) or "Notes" in m.group(3) or "XYZ" in m.group(2)+m.group(3): print("   ", m.group(1), repr(m.group(2)[:50]), repr(m.group(3)[:50]))
m=re.search(r"<paragraph[^>]*name=\"Click to add Notes\"[^>]*screencoord=\"\((\d+), (\d+)\)\"[^>]*size=\"\((\d+), (\d+)\)\"", t)
open("/tmp/vk_nc","w").write("%d %d" % (int(m[1])+int(m[3])//2, int(m[2])+int(m[4])//2) if m else "")'; }
$X key Escape; sleep 1; $X key alt+v; sleep 1; $X key e; sleep 4   # View > Notes
echo "notes view:"; notes; c=$(cat /tmp/vk_nc); echo "placeholder at: $c"
[ -n "$c" ] && { $X mousemove $c click 1; sleep 1; $X type --delay 50 "XYZ Team Members"; sleep 3; }
echo "after typing (still in edit mode):"; notes
curl -s -m 30 http://$ip:5000/screenshot -o /tmp/vk_imp.png
$X key Escape; sleep 1; $X key Escape; sleep 3
echo "after Escape (left edit mode):"; notes
curl -s -m 30 http://$ip:5000/screenshot -o /tmp/vk_imp2.png
