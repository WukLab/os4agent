#!/bin/bash
# same /accessibility timing in a podman container (direct, no proxy): desktop + LibreOffice Calc
P="sudo env CONTAINERS_STORAGE_CONF=/mnt/btrfs/podman/storage.conf CONTAINERS_CONF=/mnt/ssd2/vikranth/osworld/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
$P rm -f a11y-probe >/dev/null 2>&1
$P run -d --name a11y-probe --cgroupns=host --security-opt seccomp=unconfined --security-opt label=disable --shm-size=2g \
  --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld \
  -c "$(cat /mnt/ssd2/os4agent/agents/osworld_rl/desk_osw.sh)" >/dev/null
ip=$($P inspect a11y-probe --format '{{.NetworkSettings.IPAddress}}')
for i in $(seq 120); do curl -fs -m 5 -o /dev/null http://$ip:5000/screenshot && break; sleep 2; done; sleep 20
$P exec a11y-probe bash -c 'su abc -c "DISPLAY=:1 setsid nohup libreoffice --calc >/dev/null 2>&1 </dev/null &"'; sleep 30
for i in 1 2 3; do echo "a11y container: $(curl -s -o /dev/null -w '%{http_code} %{time_total}s' -m 300 http://$ip:5000/accessibility)"; done
$P rm -f a11y-probe >/dev/null 2>&1
