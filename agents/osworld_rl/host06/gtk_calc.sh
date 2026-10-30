#!/bin/bash
# In imp-test (libreoffice-gtk3 installed): open the Calc task's xlsx with the GTK3 backend; report the document role,
# cells in the tree and their text.
cd /mnt/ssd2/vikranth/osworld
P="env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
X=/tmp/vk_w/NetIncome.xlsx
$P exec imp-test pkill -f soffice; sleep 2
$P cp "$X" imp-test:/config/NetIncome.xlsx; $P exec imp-test chown abc:abc /config/NetIncome.xlsx
$P exec imp-test bash -c 'setsid nohup setpriv --reuid=abc --regid=abc --init-groups -- env HOME=/config DISPLAY=:1 XDG_RUNTIME_DIR=/config/.XDG SAL_USE_VCLPLUGIN=gtk3 GTK_MODULES=gail:atk-bridge NO_AT_BRIDGE=0 soffice --calc /config/NetIncome.xlsx >/tmp/lo.log 2>&1 < /dev/null &'
sleep 25
ip=$($P inspect -f "{{.NetworkSettings.IPAddress}}" imp-test)
curl -s -m 90 http://$ip:5000/accessibility | python3 -c '
import json,sys,re
t=json.load(sys.stdin).get("AT") or ""
print("tree chars", len(t), "| doc roles:", sorted(set(re.findall(r"<(document-[a-z]+)", t))))
cells=re.findall(r"<table-cell name=\"([A-Z]+[0-9]+)\"[^>]*>([^<]*)", t)
print("cells:", len(cells), "| first/last:", cells[:1], cells[-1:], "| with text:", sum(1 for _,x in cells if x.strip()))
print([c for c in cells if c[1].strip()][:12])'
curl -s -m 30 http://$ip:5000/screenshot -o /tmp/vk_gtk.png
