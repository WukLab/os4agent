#!/bin/bash
# What are restoring tasks blocked on when concurrent 8-copy tfork clones time out? Samples kernel state of all criu/restore threads.
cd /mnt/ssd2/vikranth/osworld; O=$PWD/traces/tfork_fix3; sudo rm -rf $O; mkdir -p $O
export CONTAINERS_STORAGE_CONF=/mnt/btrfs/podman/storage.conf CONTAINERS_CONF=/mnt/ssd2/vikranth/osworld/containers-os4agent.conf
P="sudo env CONTAINERS_STORAGE_CONF=$CONTAINERS_STORAGE_CONF CONTAINERS_CONF=$CONTAINERS_CONF PODMAN_TFORK_NO_REAP=1 /mnt/ssd2/os4agent/podman-tfork.sh"
DESK=$(cat /mnt/ssd2/os4agent/agents/osworld_rl/desk_osw.sh)
$P ps -a --format "{{.Names}}" | xargs -r -n 20 $P rm -f >/dev/null 2>&1
for i in 0 1 2 3; do
  $P run -d --name prof-d$i --cgroupns=host --ulimit nofile=1048576:1048576 --security-opt seccomp=unconfined --security-opt label=disable \
    --shm-size=2g --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$DESK" >/dev/null
done
for i in 0 1 2 3; do ip=$($P inspect prof-d$i --format '{{.NetworkSettings.IPAddress}}'); for k in $(seq 120); do curl -fs -m 5 -o /dev/null http://$ip:5000/screenshot && break; sleep 2; done; done
sleep 30; for i in 0 1 2 3; do $P exec prof-d$i bash -c 'su abc -c "DISPLAY=:1 setsid nohup gimp >/dev/null 2>&1 </dev/null &"'; done; sleep 40
clone() { $P exec $1 true; sleep 0.1; local t0=$(date +%s.%N)   # <src> <tag> <extra clone flags...>
  $P container clone --live --copies=8 --tfork-tcp-close --tfork-ghost-limit=67108864 "${@:3}" --name $1-$2 $1 > $O/$2-$1.out 2>&1
  echo "$2 $1 rc=$? secs=$(echo "$(date +%s.%N) - $t0" | bc)" >> $O/summary.txt; }
rmclones() { $P ps -a --format "{{.Names}}" | grep -v "^prof-d[0-9]$" | xargs -r -n 20 $P rm -f >/dev/null 2>&1; }
sample() {   # <tag>: every 1 s for 15 s, all D-state (uninterruptible) threads host-wide: wchan + kernel stack, grouped
  for s in $(seq 15); do
    sleep 1; f=$O/$1-t$s.txt; echo "load $(cut -d' ' -f1-3 /proc/loadavg) $(grep procs_ /proc/stat | tr '\n' ' ')" > $f
    ps -eLo stat=,wchan:40=,comm= | awk '$1 ~ /^D/' | awk '{print $2, $3}' | sort | uniq -c | sort -rn | head -15 >> $f
    n=0; for t in $(ps -eLo stat=,tid= | awk '$1 ~ /^D/ {print $2}'); do
      st=$(cat /proc/$t/stack 2>/dev/null | sed -E 's/\+0x[0-9a-f]+\/0x[0-9a-f]+//; s/^\[<0>\] //' | head -12 | tr '\n' ' ')
      [ -n "$st" ] && echo "$st"; n=$((n+1)); [ $n -ge 400 ] && break
    done | sort | uniq -c | sort -rn | head -6 | sed 's/^/STACK /' >> $f
  done; }
run4() {   # <tag> <flags...>: 4 concurrent 8-copy clones, then a host I/O snapshot
  for i in 0 1 2 3; do clone prof-d$i $1 "${@:2}" & done; wait; rmclones; sleep 20; }
run4 overlay_r1 --persistent=async --tfork-overlay-btrfs
run4 overlay_r2 --persistent=async --tfork-overlay-btrfs
run4 overlay_r3 --persistent=async --tfork-overlay-btrfs
run4 overlay_r4 --persistent=async --tfork-overlay-btrfs
run4 overlay_r5 --persistent=async --tfork-overlay-btrfs
run4 overlay_r6 --persistent=async --tfork-overlay-btrfs
$P ps -a --format "{{.Names}}" | xargs -r -n 20 $P rm -f >/dev/null 2>&1
sudo chown -R vikranth:vikranth $O; touch $O/DONE
