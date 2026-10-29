#!/bin/bash
# Remove leftover recording environments (wa_record.py names them wa-<run>-w<wave>-t<task>-g<k>) and report.
#   sudo bash agents/webarena_rl/setup/cleanup_recording.sh [name-prefix]        (default: wa-, i.e. every recording)
# podman serialises removals on its storage lock (~8 s per WebArena container), so this kills them all first (fast,
# frees CPU and memory), then removes them in batches.
set -u
HERE=$(cd "$(dirname "$0")/.." && pwd); REPO=$(cd "$HERE/../.." && pwd)
P="env CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf CONTAINERS_CONF=$HERE/containers-os4agent.conf $REPO/podman-tfork.sh"
PREFIX=${1:-wa-}
names=$($P ps -a --format '{{.Names}}' | grep "^$PREFIX" || true)
n=$(echo -n "$names" | grep -c . || true)
echo "$(date +%T) $n containers matching ^$PREFIX"
[ "$n" = 0 ] && exit 0
echo "$names" | xargs -r -n 50 $P kill -s KILL > /dev/null 2>&1
echo "$(date +%T) killed"
echo "$names" | xargs -r -n 50 $P rm -f -t 0 > /dev/null 2>&1
echo "$(date +%T) removed; left: $($P ps -a --format '{{.Names}}' | grep -c "^$PREFIX")"
