#!/bin/bash
# restore errors from failed tfork bundles kept during the replay32_tfork run (retries set PODMAN_TFORK_NO_REAP)
cd /mnt/btrfs/podman/storage/tfork-bundles || exit 1
for b in $(ls -t | head -60); do
  f=$(ls $b/img/tfork-restore.log.copy* 2>/dev/null | head -1); [ -n "$f" ] || continue
  grep -q "Error" $f || continue
  echo "== ${b:0:12} $(stat -c %y $b | cut -c12-19) $(grep -h '"name"' $b/config.json 2>/dev/null | head -0)"
  grep -h "Error\|Warn" $b/img/tfork-restore.log.copy* | sed -E 's/^\([ 0-9.]+\) +//; s/[0-9]{3,}/N/g' | sort | uniq -c | sort -rn | head -6
done | head -45
