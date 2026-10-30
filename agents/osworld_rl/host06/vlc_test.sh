#!/bin/bash
# VLC stream render check: launch VLC like task bba3381f, play the HLS URL via VLC's HTTP API, screenshot + status.
# Usage: vlc_test.sh [extra vlc args]
cd /mnt/ssd2/vikranth/osworld
P="env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
URL=https://devstreaming-cdn.apple.com/videos/streaming/examples/img_bipbop_adv_example_fmp4/master.m3u8
$P rm -f vlc-test >/dev/null 2>&1
$P run -d --name vlc-test --cgroupns=host --security-opt seccomp=unconfined --security-opt label=disable --shm-size=2g \
  --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$(cat desk_osw.sh)" >/dev/null
sleep 35
$P exec vlc-test bash -c "grep -rhs '^[a-z].*=' /config/.config/vlc/vlcrc | grep -E 'http|extraintf|vout|avcodec-hw|password' | head; cat /tmp/vk_vlc.log 2>/dev/null"
$P exec vlc-test bash -c "setsid nohup setpriv --reuid=abc --regid=abc --init-groups -- env HOME=/config DISPLAY=:1 VLC_VERBOSE=1 vlc --no-audio --no-video-title-show $* >/tmp/vlc.log 2>&1 < /dev/null &"
sleep 8
ip=$($P inspect -f "{{.NetworkSettings.IPAddress}}" vlc-test)
$P exec vlc-test bash -c "curl -s -u :password 'http://localhost:8080/requests/status.xml?command=in_play&input=$URL' | grep -E '<state>' "
sleep 25
$P exec vlc-test bash -c "curl -s -u :password http://localhost:8080/requests/status.xml | grep -E '<state>|<time>|<length>|<resolution>|name=.filename'"
curl -s -m 30 http://$ip:5000/screenshot -o /tmp/vk_vlc.png; ls -la /tmp/vk_vlc.png
$P exec vlc-test bash -c "grep -iE 'error|vout|decoder|video output|failed' /tmp/vlc.log | sort | uniq -c | sort -rn | head -25"
