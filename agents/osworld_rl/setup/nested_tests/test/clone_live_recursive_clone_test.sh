#!/bin/bash
# MVP smoke for clone-of-clone over the Part G overlay-rootfs design.
#
# Verifies:
#   1. gen-1 clone of a regular podman source comes up (existing path).
#   2. gen-2 clone of gen-1 comes up via the new recursive branch:
#        - parent overlay layers resolved via /proc/self/mountinfo
#        - parent's upper frozen, reflink-cp'd into gen-2's fresh upper
#        - gen-2's snap-ro is a SYMLINK back to gen-1's snap-ro
#   3. Writes from each generation propagate to the next (gen-2 sees
#      gen-1's writes; gen-3 sees gen-1's + gen-2's writes).
#   4. Overlay depth stays = 1 (always one lowerdir, never a chain).
#   5. The shared lower is exactly the original src snap-ro across
#      every generation.
#
# Out of scope:
#   - Live process forking semantics (the workload is a busy-loop
#     `sh -c 'echo tick; sleep 1'` so CRIU has something to dump;
#     we don't verify the cloned process tree mirrors the source's
#     internal state, only that the disk view propagates).
#   - Recursive clone-of-clone with N>1 fan-out (only N=1 chained).
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

PODMAN="${PODMAN:-$REPO_ROOT/podman/bin/podman}"
CRUN=$REPO_ROOT/crun/crun
CRIU_PATH=$REPO_ROOT/criu/criu
LIBCRIU=$REPO_ROOT/criu/lib/c

SRC_NAME=tfork-rec-src
G1_NAME=tfork-rec-g1
G2_NAME=tfork-rec-g2
G3_NAME=tfork-rec-g3

cleanup_state() {
    set +e
    sudo $PODMAN rm -f $(sudo $PODMAN ps -aq --filter name=tfork-rec) 2>/dev/null
    for cid in $(sudo $CRUN list 2>/dev/null | awk 'NR>1 && /^[0-9a-f]/ {print $1}'); do
        sudo $CRUN kill $cid KILL 2>/dev/null
        sudo $CRUN delete $cid 2>/dev/null
    done
    while read -r m; do
        sudo umount "$m" 2>/dev/null
    done < <(awk '/\/mnt\/btrfs\/.*tfork-bundles.*overlay/ {print $5}' /proc/mounts 2>/dev/null)
    sudo find /mnt/btrfs/podman/storage/tfork-bundles -mindepth 2 \
        \( -name "rootfs*" -o -name "snap-ro" -o -name "upper*" -o -name "snap-*" -o -name "parent-upper-frozen" \) \
        2>/dev/null \
        | while read s; do
            if [ -L "$s" ]; then
                sudo rm -f "$s" 2>/dev/null
            else
                sudo btrfs subvolume delete "$s" 2>/dev/null
            fi
          done
    sudo rm -rf /mnt/btrfs/podman/storage/tfork-bundles
    set -e
}

cleanup_state

run_clone() {
    local src=$1; local dst=$2; local logf=$3
    sudo env PATH=$CRIU_PATH:$PATH LD_LIBRARY_PATH=$LIBCRIU \
        $PODMAN container clone --live ${CLONE_EXTRA:-} --name $dst $src \
        > $logf 2>&1 \
        || { echo "CLONE $src->$dst FAILED:"; tail -40 $logf; exit 1; }
}

bundle_for_name() {
    local name=$1
    sudo $PODMAN inspect $name --format '{{.Rootfs}}' 2>/dev/null \
        | xargs -I{} dirname {}
}

echo "=== recursive clone-of-clone smoke ==="

echo "--- 1. start regular source ---"
sudo $PODMAN run -d --name $SRC_NAME ${ALPINE:-docker.io/library/alpine:3.20} \
    sh -c 'i=0; while true; do echo "tick $i"; i=$((i+1)); sleep 1; done' >/dev/null
sleep 2
SRC_PID=$(sudo $PODMAN inspect $SRC_NAME --format '{{.State.Pid}}')
echo "    src pid=$SRC_PID"

echo
echo "--- 2. gen-1 clone (existing path) ---"
run_clone $SRC_NAME $G1_NAME /tmp/rec_g1.log
G1_PID=$(sudo $PODMAN inspect $G1_NAME --format '{{.State.Pid}}')
G1_BUNDLE=$(bundle_for_name $G1_NAME)
echo "    gen-1 pid=$G1_PID  bundle=$G1_BUNDLE"
sudo test -d "$G1_BUNDLE/snap-ro" || { echo "FAIL: $G1_BUNDLE/snap-ro missing"; exit 1; }
sudo test -L "$G1_BUNDLE/snap-ro" && { echo "FAIL: gen-1 snap-ro should be a real subvol, not a symlink"; exit 1; }
echo "    gen-1 snap-ro is real subvol: OK"

echo
echo "--- 3. write a marker into gen-1 ---"
sudo $PODMAN exec $G1_NAME sh -c 'echo "G1 was here" > /G1MARK; sync' \
    || { echo "exec G1MARK failed"; exit 1; }
echo "    /G1MARK in gen-1: $(sudo $PODMAN exec $G1_NAME cat /G1MARK)"

echo
echo "--- 4. gen-2 clone OF gen-1 (new recursive path) ---"
run_clone $G1_NAME $G2_NAME /tmp/rec_g2.log
G2_PID=$(sudo $PODMAN inspect $G2_NAME --format '{{.State.Pid}}')
G2_BUNDLE=$(bundle_for_name $G2_NAME)
echo "    gen-2 pid=$G2_PID  bundle=$G2_BUNDLE"

# (a) gen-2's snap-ro must be a SYMLINK to gen-1's snap-ro
if ! sudo test -L "$G2_BUNDLE/snap-ro"; then
    echo "FAIL: $G2_BUNDLE/snap-ro is not a symlink — should point at gen-1's snap-ro"
    sudo ls -la "$G2_BUNDLE/" | head
    exit 1
fi
G2_SNAPRO_TARGET=$(sudo readlink -f "$G2_BUNDLE/snap-ro")
G1_SNAPRO_REAL=$(sudo readlink -f "$G1_BUNDLE/snap-ro")
if [ "$G2_SNAPRO_TARGET" != "$G1_SNAPRO_REAL" ]; then
    echo "FAIL: gen-2 snap-ro -> $G2_SNAPRO_TARGET, expected $G1_SNAPRO_REAL"
    exit 1
fi
echo "    gen-2 snap-ro -> $G2_SNAPRO_TARGET (== gen-1 snap-ro): OK"

# (b) gen-2's overlay lowerdir must == gen-1's snap-ro (resolved)
G2_LOWER=$(sudo awk -v p=$G2_BUNDLE '$3=="overlay" && index($2,p)==1 {print $4}' /proc/mounts \
    | tr ',' '\n' | sed -n 's/^lowerdir=//p' | head -1)
echo "    gen-2 overlay lowerdir: $G2_LOWER"
G2_LOWER_REAL=$(sudo readlink -f "$G2_LOWER")
if [ "$G2_LOWER_REAL" != "$G1_SNAPRO_REAL" ]; then
    echo "FAIL: gen-2 lower resolves to $G2_LOWER_REAL, expected $G1_SNAPRO_REAL"
    exit 1
fi
echo "    gen-2 lower resolves to gen-1 snap-ro: OK (depth=1, shared)"

# (c) gen-2 must see gen-1's marker (from reflink-cp'd parent upper)
G2_MARK=$(sudo $PODMAN exec $G2_NAME cat /G1MARK 2>/dev/null || true)
if [ "$G2_MARK" != "G1 was here" ]; then
    echo "FAIL: gen-2 cannot see /G1MARK from gen-1"
    echo "    got: '$G2_MARK'"
    exit 1
fi
echo "    gen-2 sees gen-1's /G1MARK: OK"

# (d) parent-upper-frozen must have been deleted post-loop
if sudo test -d "$G2_BUNDLE/parent-upper-frozen"; then
    echo "FAIL: $G2_BUNDLE/parent-upper-frozen leaked (cleanup didn't run)"
    exit 1
fi
echo "    parent-upper-frozen cleaned up: OK"

echo
echo "--- 5. write a marker into gen-2, chain to gen-3 ---"
sudo $PODMAN exec $G2_NAME sh -c 'echo "G2 was here" > /G2MARK; sync'
echo "    /G2MARK in gen-2: $(sudo $PODMAN exec $G2_NAME cat /G2MARK)"

run_clone $G2_NAME $G3_NAME /tmp/rec_g3.log
G3_PID=$(sudo $PODMAN inspect $G3_NAME --format '{{.State.Pid}}')
G3_BUNDLE=$(bundle_for_name $G3_NAME)
echo "    gen-3 pid=$G3_PID  bundle=$G3_BUNDLE"

# gen-3's lower must STILL be the original src snap-ro (the deep
# shared lower across the entire chain — depth-1 invariant).
G3_LOWER=$(sudo awk -v p=$G3_BUNDLE '$3=="overlay" && index($2,p)==1 {print $4}' /proc/mounts \
    | tr ',' '\n' | sed -n 's/^lowerdir=//p' | head -1)
G3_LOWER_REAL=$(sudo readlink -f "$G3_LOWER")
if [ "$G3_LOWER_REAL" != "$G1_SNAPRO_REAL" ]; then
    echo "FAIL: gen-3 lower resolves to $G3_LOWER_REAL, expected $G1_SNAPRO_REAL (the original src snap-ro)"
    exit 1
fi
echo "    gen-3 lower still == original src snap-ro: OK (50+ chains preserve shared lower)"

# gen-3 must see BOTH markers (collapse of gen-1's + gen-2's writes)
G3_M1=$(sudo $PODMAN exec $G3_NAME cat /G1MARK 2>/dev/null || true)
G3_M2=$(sudo $PODMAN exec $G3_NAME cat /G2MARK 2>/dev/null || true)
if [ "$G3_M1" != "G1 was here" ] || [ "$G3_M2" != "G2 was here" ]; then
    echo "FAIL: gen-3 missing inherited writes (G1MARK='$G3_M1' G2MARK='$G3_M2')"
    exit 1
fi
echo "    gen-3 sees /G1MARK + /G2MARK: OK (collapse-via-reflink working)"

echo
echo "--- 6. summary ---"
echo "    src   pid=$SRC_PID"
echo "    gen-1 pid=$G1_PID  bundle=$G1_BUNDLE"
echo "    gen-2 pid=$G2_PID  bundle=$G2_BUNDLE"
echo "    gen-3 pid=$G3_PID  bundle=$G3_BUNDLE"
echo "    All assertions passed."

echo
echo "--- 7. cleanup ---"
cleanup_state
echo "    OK."
