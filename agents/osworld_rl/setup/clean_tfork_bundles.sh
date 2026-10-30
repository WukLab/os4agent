#!/bin/bash
# Remove tfork bundles left on disk (kept by PODMAN_TFORK_NO_REAP=1 or by killed clones). Run as root with no containers.
STORAGE_CONF=${STORAGE_CONF:-/mnt/ssd3/podman/storage.conf}
B=${1:-$(dirname "$STORAGE_CONF")/storage/tfork-bundles}
HERE=$(cd "$(dirname "$0")/.." && pwd)
P="env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=$STORAGE_CONF CONTAINERS_CONF=$HERE/containers-os4agent.conf ${OS4AGENT:-/mnt/ssd2/os4agent}/podman-tfork.sh"
[ "$($P ps -aq | wc -l)" = 0 ] || { echo "containers exist; remove them first" >&2; exit 1; }
for b in "$B"/*/; do
  b=${b%/}
  awk -v p="$b/" 'index($2, p) == 1 {print $2}' /proc/mounts | sort -r | while read -r m; do umount -l "$m"; done
  [ -d "$b/snap-ro" ] && btrfs subvolume delete "$b/snap-ro" >/dev/null
  rm -rf "$b"
done
echo "left: $(ls "$B" | wc -l) bundles, $(grep -c " $B/" /proc/mounts) mounts"
