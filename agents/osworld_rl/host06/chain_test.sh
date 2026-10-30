#!/bin/bash
# Does stopping a NON-persistent overlay clone break forks of its child? Chain: source -> G (2 copies, persistent, like a
# group fork) -> S1 = fork of G0 (2 copies, no --persistent, like a spec fork) -> keep S1-0, rm S1-1 -> S2 = fork of S1-0 ->
# STOP S1-0 (what a hit does) and rm S2-1 -> fork S2-0 again. Prints ok/fail per fork. Removes everything it made.
cd /mnt/ssd2/vikranth/osworld
P="env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
G="--tfork-tcp-close --tfork-ghost-limit=67108864 --tfork-overlay-btrfs"
clone() { out=$($P container clone --live "$@" 2>&1); rc=$?; ids=($(echo "$out" | grep -E "^[0-9a-f]{64}$")); echo "  clone $* -> rc=$rc ${#ids[@]} copies $([ $rc != 0 ] && echo "$out" | grep -o "Error: .*" | tail -1 | cut -c1-200)"; }
$P ps -a --format "{{.Names}}" | grep "^ct-" | xargs -r $P rm -f -t 0 >/dev/null 2>&1
$P run -d --name ct-src --cgroupns=host --ulimit nofile=1048576:1048576 --security-opt seccomp=unconfined --security-opt label=disable \
  --shm-size=2g --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$(cat desk_osw.sh)" >/dev/null
sleep 45
echo "G: group fork, persistent"; clone --copies=2 --persistent=async $G --name ct-g ct-src; G0=${ids[0]}
echo "S1: fork of G0, no persistent"; clone --copies=2 $G --name ct-s1 $G0; S1a=${ids[0]}; S1b=${ids[1]}
$P rm -f -t 0 $S1b >/dev/null; echo "  removed loser S1-1"
echo "S2: fork of S1-0 (the adopted fork)"; clone --copies=2 $G --name ct-s2 $S1a; S2a=${ids[0]}; S2b=${ids[1]}
$P stop -t 0 $S1a >/dev/null; $P rm -f -t 0 $S2b >/dev/null; echo "  stopped S1-0 (old desktop after a hit), removed loser S2-1"
echo "S3: fork of S2-0 (the next speculation)"; clone --copies=2 $G --name ct-s3 $S2a
$P ps -a --format "{{.Names}}" | grep "^ct-" | xargs -r $P rm -f -t 0 >/dev/null 2>&1; echo "cleaned: $($P ps -a --format "{{.Names}}" | grep -c "^ct-") ct- containers left"
