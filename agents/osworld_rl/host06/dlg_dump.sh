#!/bin/bash
# Raw a11y XML of Writer's Format > Character dialog on a desktop started like osw_run (GTK3 plugin, live desk_osw.sh).
cd /mnt/ssd2/vikranth/osworld
P="env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
C=dlg-test
$P rm -f $C >/dev/null 2>&1
$P run -d --name $C --cgroupns=host --security-opt seccomp=unconfined --security-opt label=disable --shm-size=2g \
  --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$(cat desk_osw.sh)" >/dev/null
$P cp lo_gtk3/libvclplug_gtk3lo.so $C:/usr/lib/libreoffice/program/
$P cp /tmp/vk_w/Novels_Intro_Packet.docx $C:/config/Desktop/n.docx; $P exec $C chown abc:abc /config/Desktop/n.docx
sleep 30
ip=$($P inspect -f "{{.NetworkSettings.IPAddress}}" $C)
curl -s -m 30 -X POST -H "Content-Type: application/json" -d '{"path": "/home/user/Desktop/n.docx"}' http://$ip:5000/setup/open_file; echo
sleep 15
X="$P exec $C env DISPLAY=:1 xdotool"
$X mousemove 900 500 click 1; sleep 1; $X key alt+o; sleep 1; $X key h; sleep 4
curl -s -m 120 http://$ip:5000/accessibility > /tmp/vk_dlg.json
curl -s -m 30 http://$ip:5000/screenshot -o /tmp/vk_dlg.png
echo "ip $ip"
