#!/bin/bash
# keep_failed_clone on a clone-of-clone bundle: does the OLD cleanup delete the group's shared snapshot R, and does the
# NEW one leave it? Per group: G = group fork (persistent), S = fork of G's copy (its batch snap-ro is a symlink to R),
# a fake failed bundle with the same symlink gets the cleanup, then S's copy is forked again.
cd /mnt/ssd2/vikranth/osworld
P="env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
F="--tfork-tcp-close --tfork-ghost-limit=67108864 --tfork-overlay-btrfs"
BUNDLES=/mnt/ssd3/podman/storage/tfork-bundles
clone() { out=$($P container clone --live "$@" 2>&1); rc=$?; ids=($(echo "$out" | grep -E "^[0-9a-f]{64}$")); [ $rc = 0 ] && msg=ok || msg="FAIL: $(echo "$out" | grep -o 'Error: .*' | tail -1 | cut -c1-160)"; }
$P ps -a --format "{{.Names}}" | grep "^cu-" | xargs -r $P rm -f -t 0 >/dev/null 2>&1
$P run -d --name cu-src --cgroupns=host --ulimit nofile=1048576:1048576 --security-opt seccomp=unconfined --security-opt label=disable \
  --shm-size=2g --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$(cat desk_osw.sh)" >/dev/null
sleep 40
for mode in old new; do
  echo "== $mode cleanup"
  clone --copies=1 --persistent=async $F --name cu-g-$mode cu-src; g=${ids[0]}; echo "  group fork: $msg"
  clone --copies=2 $F --name cu-s-$mode $g; s=${ids[0]}; echo "  fork of group copy: $msg"
  lower=$(grep " $($P inspect -f '{{.Rootfs}}' $s) overlay" /proc/mounts | grep -o "lowerdir=[^,]*" | cut -d= -f2)
  R=$(readlink -f $lower); echo "  fork's lower: $lower -> R = $R  (symlink: $([ -L $lower ] && echo yes || echo no))"
  [ -n "$R" ] && [ -d "$R" ] || { echo "  no R found, skipping"; continue; }
  fake=$BUNDLES/cu-fake-$mode; mkdir -p $fake; ln -s $R $fake/snap-ro     # what a failed clone of $s leaves behind
  if [ $mode = old ]; then   # osw_run.py before the fix
    [ -d $fake/snap-ro ] && btrfs subvolume delete $fake/snap-ro >/dev/null 2>&1
  else                        # after the fix
    if [ -L $fake/snap-ro ]; then rm $fake/snap-ro; elif [ -d $fake/snap-ro ]; then btrfs subvolume delete $fake/snap-ro >/dev/null 2>&1; fi
  fi
  rm -rf $fake
  echo "  after cleanup: R exists: $([ -d $R ] && echo yes || echo NO)"
  clone --copies=2 $F --name cu-s2-$mode $s; echo "  fork again (next speculation): $msg"
done
$P ps -a --format "{{.Names}}" | grep "^cu-" | xargs -r $P rm -f -t 0 >/dev/null 2>&1
echo "cleaned: $($P ps -a --format '{{.Names}}' | grep -c '^cu-') cu- containers left"
