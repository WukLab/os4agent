#!/usr/bin/env bash
# Stop aenv-server if /mnt/data/btrfs drops below MIN_GB free (default 50: the per-disk floor), e.g. during the
# template conversion, which needed >194 GB of scratch space for the 62 GB WebArena image. Runs until killed.
#   bash agents/webarena_rl/setup/aenv/disk_guard.sh [MIN_GB]  > log &
MIN_GB=${1:-50}
while true; do
    free=$(df -BG --output=avail /mnt/data/btrfs | tail -1 | tr -dc 0-9)
    if [ "$free" -lt "$MIN_GB" ]; then
        echo "$(date +%T) btrfs free ${free} GB < ${MIN_GB} GB: stopping aenv-server"
        docker stop -t 20 aenv-server
        exit 1
    fi
    sleep 5
done
