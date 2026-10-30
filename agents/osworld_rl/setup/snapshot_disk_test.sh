#!/bin/bash
# How much disk a persistent tfork snapshot of one OSWorld desktop uses on the btrfs podman store: the memory image
# (img/) vs the rootfs (snap-ro, a btrfs snapshot that should share every file extent with the container).
#   sudo bash setup/snapshot_disk_test.sh [storage.conf]       (default /mnt/ssd3/podman/storage.conf)
set -u
cd "$(dirname "$0")/.."
SC=${1:-/mnt/ssd3/podman/storage.conf}
ROOT=$(dirname "$SC")/storage
FS=$(df --output=target "$ROOT" | tail -1)
P="env PODMAN_TFORK_SKIP_SYSCTL=1 PODMAN_TFORK_NO_REAP=1 CONTAINERS_STORAGE_CONF=$SC CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
SRC=snaptest-src
free() { df -B1 --output=avail "$FS" | tail -1; }
gib() { awk -v b="$1" 'BEGIN {printf "%.2f GiB", b / 2^30}'; }
bdu() { btrfs filesystem du -s --raw "$1" 2>/dev/null | tail -1 | awk '{print $1, $2, $3}'; }  # total exclusive shared
report() {  # bundle label
  local b=$1 label=$2
  echo "== $label: $b"
  for part in img snap-ro; do
    [ -e "$b/$part" ] || continue
    read -r tot exc sh <<<"$(bdu "$b/$part")"
    echo "   $part: total $(gib "$tot"), exclusive $(gib "$exc"), shared with other files $(gib "$sh")"
  done
  for u in "$b"/upper-*; do [ -d "$u" ] && echo "   $(basename "$u"): $(du -sb "$u" | cut -f1 | xargs -I{} awk -v b={} 'BEGIN {printf "%.1f MiB", b / 2^20}')"; done
}

$P rm -f -t 0 $SRC >/dev/null 2>&1
$P run -d --name $SRC --cgroupns=host --ulimit nofile=1048576:1048576 --security-opt seccomp=unconfined \
  --security-opt label=disable --shm-size=2g --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m \
  --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$(cat desk_osw.sh)" >/dev/null
echo "desktop started; letting it settle 60 s"; sleep 60
pid=$($P inspect -f '{{.State.Pid}}' $SRC)
cg=/sys/fs/cgroup$(cut -d: -f3- /proc/$pid/cgroup)
echo "source desktop: memory.current $(gib "$(cat $cg/memory.current)"), anon $(gib "$(awk '/^anon / {print $2}' $cg/memory.stat)")"
echo "rootfs image size: $($P image inspect -f '{{.Size}}' ghcr.io/wuklab/webtop:ubuntu-kde-osworld | xargs -I{} awk -v b={} 'BEGIN {printf "%.2f GiB", b / 2^30}')"
$P exec $SRC true; sleep 0.1

for mode in ckpt overlay; do
  before=$(free); t0=$(date +%s.%N)
  if [ $mode = ckpt ]; then
    out=$($P container clone --live --copies=1 --persistent=sync --tfork-tcp-close --tfork-ghost-limit=67108864 --name snaptest-ckpt $SRC 2>&1)
    rc=$?
  else
    out=$($P container clone --live --copies=8 --persistent=async --tfork-tcp-close --tfork-ghost-limit=67108864 \
          --tfork-overlay-btrfs --name snaptest-ov $SRC 2>&1)
    rc=$?
    sleep 20  # async: let the image finish writing
  fi
  t1=$(date +%s.%N); sync; sleep 3
  b=$(ls -td "$ROOT"/tfork-bundles/*/ 2>/dev/null | head -1); b=${b%/}
  echo; echo "### $mode clone: rc=$rc, $(awk -v a="$t0" -v b="$t1" 'BEGIN {printf "%.1f s", b - a}'), free space dropped by $(gib $((before - $(free))))"
  [ $rc = 0 ] || { echo "$out" | grep -iE "error" | head -5; grep -E "Error" "$b/crun-tfork.log" | head -4; }
  report "$b" "$mode bundle"
  echo "   whole bundle: $(du -sb --exclude=snap-ro --exclude='rootfs*' "$b" | cut -f1 | xargs -I{} awk -v b={} 'BEGIN {printf "%.2f GiB", b / 2^30}') outside the rootfs"
done

echo; echo "cleaning up"
$P ps -aq | xargs -r $P rm -f -t 0 >/dev/null 2>&1
for b in "$ROOT"/tfork-bundles/*/; do
  b=${b%/}
  awk -v p="$b/" 'index($2, p) == 1 {print $2}' /proc/mounts | sort -r | while read -r m; do umount -l "$m"; done
  [ -d "$b/snap-ro" ] && btrfs subvolume delete "$b/snap-ro" >/dev/null
  rm -rf "$b"
done
echo "done; free space now $(gib "$(free)")"
