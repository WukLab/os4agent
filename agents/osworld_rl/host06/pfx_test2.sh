#!/bin/bash
# prefix-cache test, --overlay-rootfs 0: B empty cache, C warm cache, then A0 = no-cache baseline at overlay 0 (memory reference)
cd /mnt/ssd2/vikranth/osworld
SC=/mnt/ssd3/podman/storage.conf; ROOT=/mnt/ssd3/podman/storage
P="env CONTAINERS_STORAGE_CONF=$SC CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
echo "cleanup: $($P ps -aq | wc -l) containers"
$P ps -aq | xargs -r $P rm -f -t 0 >/dev/null 2>&1
for b in $ROOT/tfork-bundles/*/; do [ -d "$b" ] || continue; b=${b%/}
  awk -v p="$b/" "index(\$2, p) == 1 {print \$2}" /proc/mounts | sort -r | while read -r m; do umount -l "$m"; done
  [ -d "$b/snap-ro" ] && btrfs subvolume delete "$b/snap-ro" >/dev/null; rm -rf "$b"; done
echo "bundles left: $(ls $ROOT/tfork-bundles | wc -l), overlay mounts left: $(grep -c tfork-bundles /proc/mounts)"
COMMON="--system tfork --tasks pfx_test_tasks.json --rollouts 8 --replay traces/grpo_tfork16_e0 --release-copies 1 --obs-timeout 600 --setup-concurrency 2 --fork-concurrency 2 --mem-limit-gib 220 --overlay-rootfs 0"
rm -rf traces/pfx_B traces/pfx_C traces/pfx_A0
venv/bin/python osw_run.py $COMMON --result-dir traces/pfx_B --prefix-cache pfx_cache --prefix-clear 1 > traces/pfx_B.log 2>&1; echo "B rc=$?"
venv/bin/python osw_run.py $COMMON --result-dir traces/pfx_C --prefix-cache pfx_cache > traces/pfx_C.log 2>&1; echo "C rc=$?"
venv/bin/python osw_run.py $COMMON --result-dir traces/pfx_A0 > traces/pfx_A0.log 2>&1; echo "A0 rc=$?"
echo done > traces/pfx_test2.done
