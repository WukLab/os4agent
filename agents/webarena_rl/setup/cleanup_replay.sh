#!/bin/bash
# Remove a stopped wa_replay.py run's environments: containers named <prefix>* (kill, then rm), then the tfork bundles
# the run kept (PODMAN_TFORK_NO_REAP): their copies' overlay mounts (rootfs-<i>) are unmounted and the read-only btrfs
# subvolume snap-ro deleted before rm. Bundles: those named in the run's src_*.json and any created after the run
# started (config.json's time; a clone in progress when the run stopped is in no src_*.json).
#   sudo bash setup/cleanup_replay.sh <container prefix> [<run dir>]
set -uo pipefail
PREFIX=$1; RUN=${2:-}
HERE="$(cd "$(dirname "$0")/../../.." && pwd)"
PT=(env CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf
    CONTAINERS_CONF="$HERE/agents/webarena_rl/containers-os4agent.conf" "$HERE/podman-tfork.sh")
BUNDLES=/mnt/data/btrfs/podman/storage/tfork-bundles
mapfile -t NAMES < <("${PT[@]}" ps -a --format '{{.Names}}' | grep "^$PREFIX")
echo "$(date +%T) ${#NAMES[@]} containers"
if [ ${#NAMES[@]} -gt 0 ]; then
    "${PT[@]}" kill -s KILL "${NAMES[@]}" >/dev/null 2>&1
fi
# podman's database lock races the killed containers' own cleanup ("database is locked"): repeat until none is left
for _ in 1 2 3 4 5; do
    mapfile -t NAMES < <("${PT[@]}" ps -a --format '{{.Names}}' | grep "^$PREFIX")
    [ ${#NAMES[@]} -eq 0 ] && break
    "${PT[@]}" rm -f -t 0 "${NAMES[@]}" >/dev/null
done
echo "$(date +%T) containers removed; $("${PT[@]}" ps -a --format '{{.Names}}' | grep -c "^$PREFIX") left"
drop() {
    awk -v p="$1/" 'index($5,p)==1 {print $5}' /proc/self/mountinfo | sort -r | while read -r m; do
        umount "$m" 2>/dev/null || umount -l "$m"; done
    [ -d "$1/snap-ro" ] && btrfs subvolume delete "$1/snap-ro" >/dev/null
    rm -rf --one-file-system "$1"
}
if [ -n "$RUN" ]; then
    for b in $( (python3 -I -c "import json,glob,sys
for p in glob.glob(sys.argv[1] + '/src_*.json'):
    b = json.load(open(p))['fork'].get('bundle')
    if b: print(b)" "$RUN"; find $BUNDLES -mindepth 1 -maxdepth 1 -type d -newer "$RUN/config.json") | sort -u); do
        [ -d "$b" ] && drop "$b"; done
fi
echo "$(date +%T) bundles left: $(ls $BUNDLES | wc -l); tfork mounts left: $(grep -c tfork-bundles /proc/self/mountinfo)"
