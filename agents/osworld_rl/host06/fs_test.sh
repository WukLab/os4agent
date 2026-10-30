#!/bin/bash
# Does VLC fullscreen show up in the agent's screenshot? Play the HLS stream, press f, wait 2 s (as env.step), screenshot.
cd /mnt/ssd2/vikranth/osworld
P="env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
URL=https://devstreaming-cdn.apple.com/videos/streaming/examples/img_bipbop_adv_example_fmp4/master.m3u8
C=fs-test
$P rm -f $C >/dev/null 2>&1
$P run -d --name $C --cgroupns=host --security-opt seccomp=unconfined --security-opt label=disable --shm-size=2g \
  --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$(cat desk_osw.sh)" >/dev/null
sleep 30
ip=$($P inspect -f "{{.NetworkSettings.IPAddress}}" $C)
curl -s -m 30 -X POST -H "Content-Type: application/json" -d "{\"command\": \"vlc --no-audio --no-video-title-show $URL\", \"shell\": true}" http://$ip:5000/setup/launch; echo
sleep 15
$P exec $C env DISPLAY=:1 xdotool search --class vlc windowactivate --sync key f
sleep 2
curl -s -m 30 http://$ip:5000/screenshot -o /tmp/vk_fs.png
$P exec $C bash -c "DISPLAY=:1 wmctrl -lG"
$P exec $C bash -c "DISPLAY=:1 xdotool search --class vlc getwindowgeometry %@ 2>/dev/null | grep -A1 Window | head -12"
$P rm -f -t 0 $C >/dev/null 2>&1
