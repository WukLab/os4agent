#!/bin/bash
# Why do tfork 8-copy clones time out under load? Profile CRIU's restore: (A) one 8-copy clone alone, (B) four 8-copy clones at once.
cd /mnt/ssd2/vikranth/osworld; O=$PWD/traces/tfork_prof; sudo rm -rf $O; mkdir -p $O
export CONTAINERS_STORAGE_CONF=/mnt/btrfs/podman/storage.conf CONTAINERS_CONF=/mnt/ssd2/vikranth/osworld/containers-os4agent.conf
P="sudo env CONTAINERS_STORAGE_CONF=$CONTAINERS_STORAGE_CONF CONTAINERS_CONF=$CONTAINERS_CONF /mnt/ssd2/os4agent/podman-tfork.sh"
PE="sudo env CONTAINERS_STORAGE_CONF=$CONTAINERS_STORAGE_CONF CONTAINERS_CONF=$CONTAINERS_CONF PODMAN_TFORK_NO_REAP=1 CRIU_TFORK_PROFILE=1 CRIU_TFORK_LOG_LEVEL=3 /mnt/ssd2/os4agent/podman-tfork.sh"
DESK=$(cat /mnt/ssd2/os4agent/agents/osworld_rl/desk_osw.sh)
echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled >/dev/null
$P ps -a --format "{{.Names}}" | xargs -r -n 20 $P rm -f >/dev/null 2>&1
for i in 0 1 2 3; do
  $P run -d --name prof-d$i --cgroupns=host --ulimit nofile=1048576:1048576 --security-opt seccomp=unconfined --security-opt label=disable \
    --shm-size=2g --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$DESK" >/dev/null
done
for i in 0 1 2 3; do ip=$($P inspect prof-d$i --format '{{.NetworkSettings.IPAddress}}'); for k in $(seq 120); do curl -fs -m 5 -o /dev/null http://$ip:5000/screenshot && break; sleep 2; done; done
sleep 30
for i in 0 1 2 3; do $P exec prof-d$i bash -c 'su abc -c "DISPLAY=:1 setsid nohup gimp >/dev/null 2>&1 </dev/null &"'; done; sleep 40   # a first-wave-like app
clone() {   # <src> <tag>
  $P exec $1 true; sleep 0.1
  local t0=$(date +%s.%N)
  $PE container clone --live --copies=8 --persistent=async --tfork-tcp-close --tfork-ghost-limit=67108864 --name $1-$2 $1 > $O/$2-$1.out 2>&1
  echo "$2 $1 rc=$? secs=$(echo "$(date +%s.%N) - $t0" | bc)" >> $O/summary.txt
  b=$(grep -o '/mnt/btrfs/[^ "]*/tfork-bundles/[0-9a-f]*' $O/$2-$1.out | head -1)
  [ -z "$b" ] && b=$(sudo ls -td /mnt/btrfs/podman/storage/tfork-bundles/*/ | head -1)
  mkdir -p $O/$2-$1; sudo bash -c "cp $b/crun-tfork.log $b/img/tfork*.log* $O/$2-$1/" 2>/dev/null
}
rmclones() { $P ps -a --format "{{.Names}}" | grep -v "^prof-d[0-9]$" | xargs -r -n 20 $P rm -f >/dev/null 2>&1; }
clone prof-d0 A; rmclones; sleep 20
for i in 0 1 2 3; do clone prof-d$i B & done; wait; rmclones
$P ps -a --format "{{.Names}}" | xargs -r -n 20 $P rm -f >/dev/null 2>&1
sudo chown -R vikranth:vikranth $O; touch $O/DONE
