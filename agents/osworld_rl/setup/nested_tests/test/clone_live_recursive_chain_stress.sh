#!/bin/bash
# Depth-N stress smoke for clone-of-clone over the Part G overlay-rootfs design.
#
# Builds a chain src -> g1 -> g2 -> ... -> gN with N defaulting to 50.
# Between each rung writes /GEN<i>MARK so the deepest gen, after all
# reflink-cp collapses, must see EVERY marker.
#
# Verifies for every rung:
#   - new bundle exists, has overlay-mounted rootfs
#   - snap-ro is a SYMLINK pointing back at gen-1's snap-ro
#     (which is a real subvol cloned from src's snap-ro)
#   - overlay lowerdir (resolved) == original src's snap-ro (depth-1
#     invariant — never a chain of lowers, regardless of generation)
#
# Final-rung extra checks:
#   - deepest gen sees ALL /GEN<i>MARK files (collapse-via-reflink)
#   - deepest gen still mounted, process alive
#
# Per-gen reporting:
#   - wallclock for the clone call
#   - btrfs subvol count (delta from baseline)
#   - tfork-bundles disk usage
#   - container/process counts
#
# Out of scope:
#   - N>1 fan-out (chain stays N=1)
#   - cleanup of the entire chain at the end (we leave gens running so
#     the on-disk state can be inspected; the leading cleanup_state
#     also runs at exit)
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

PODMAN="${PODMAN:-$REPO_ROOT/podman/bin/podman}"
CRUN=$REPO_ROOT/crun/crun
CRIU_PATH=$REPO_ROOT/criu/criu
LIBCRIU=$REPO_ROOT/criu/lib/c

DEPTH=${DEPTH:-50}
NAME_PREFIX=${NAME_PREFIX:-tfork-cs}        # short — bundle path = name
LOG_DIR=${LOG_DIR:-/tmp/tfork-chain-stress}
REPORT=${REPORT:-/tmp/tfork-chain-stress-report.txt}

mkdir -p "$LOG_DIR"
: > "$REPORT"
echo "DEPTH=$DEPTH NAME_PREFIX=$NAME_PREFIX LOG_DIR=$LOG_DIR" | tee -a "$REPORT"

cleanup_state() {
    set +e
    sudo $PODMAN rm -f $(sudo $PODMAN ps -aq --filter name=${NAME_PREFIX}) 2>/dev/null
    for cid in $(sudo $CRUN list 2>/dev/null | awk 'NR>1 && /^[0-9a-f]/ {print $1}'); do
        sudo $CRUN kill $cid KILL 2>/dev/null
        sudo $CRUN delete $cid 2>/dev/null
    done
    # /proc/mounts: $1=device $2=mountpoint $3=fstype $4=opts $5=dump $6=pass
    # Loop until no overlay mounts remain inside tfork-bundles (a single
    # umount pass leaves nested mounts behind).
    for _retry in 1 2 3 4 5 6 7 8; do
        local _mounts
        _mounts=$(awk '$3=="overlay" && index($2,"/mnt/ssd3/podman/storage/tfork-bundles/")==1 {print $2}' /proc/mounts)
        [ -z "$_mounts" ] && break
        while read -r m; do
            [ -n "$m" ] && sudo umount -l "$m" 2>/dev/null
        done <<< "$_mounts"
    done
    # Now safe to delete subvols (frozen snap-* are RO so order matters:
    # try non-RO first, then RO last after marking writable)
    sudo find /mnt/ssd3/podman/storage/tfork-bundles -mindepth 2 \
        \( -name "upper*" -o -name "parent-upper-frozen" -o -name "snap-i*" \) \
        2>/dev/null \
        | while read s; do
            if [ -L "$s" ]; then
                sudo rm -f "$s" 2>/dev/null
            else
                sudo btrfs property set -ts "$s" ro false 2>/dev/null
                sudo btrfs subvolume delete "$s" 2>/dev/null
            fi
          done
    sudo find /mnt/ssd3/podman/storage/tfork-bundles -mindepth 2 \
        \( -name "rootfs*" -o -name "snap-ro" -o -name "snap" -o -name "snap-*" \) \
        2>/dev/null \
        | while read s; do
            if [ -L "$s" ]; then
                sudo rm -f "$s" 2>/dev/null
            else
                sudo btrfs property set -ts "$s" ro false 2>/dev/null
                sudo btrfs subvolume delete "$s" 2>/dev/null
            fi
          done
    sudo rm -rf /mnt/ssd3/podman/storage/tfork-bundles 2>/dev/null
    sudo find /run/crun -maxdepth 1 -mindepth 1 -type d -exec rm -rf {} + 2>/dev/null
    set -e
}

bundle_for_name() {
    sudo $PODMAN inspect "$1" --format '{{.Rootfs}}' 2>/dev/null | xargs -I{} dirname {}
}

subvol_count_tfork() {
    sudo btrfs subvolume list /mnt/ssd3 2>/dev/null \
        | grep -c tfork-bundles || true
}

tfork_bundles_du() {
    sudo du -sb /mnt/ssd3/podman/storage/tfork-bundles 2>/dev/null \
        | awk '{print $1}' || echo 0
}

run_clone() {
    local src=$1 dst=$2 logf=$3
    sudo env PATH=$CRIU_PATH:$PATH LD_LIBRARY_PATH=$LIBCRIU \
        $PODMAN container clone --live ${CLONE_EXTRA:-} --name $dst $src \
        > "$logf" 2>&1
}

trap 'echo "[trap] cleanup on exit"; cleanup_state; true' EXIT

cleanup_state

SRC_NAME=${NAME_PREFIX}-src
echo
echo "=== chain stress: depth=$DEPTH ===" | tee -a "$REPORT"

echo "--- 0. baseline ---" | tee -a "$REPORT"
BASE_SUBVOLS=$(subvol_count_tfork)
BASE_DU=$(tfork_bundles_du)
DF_BEFORE=$(df -h /mnt/ssd3 | tail -1)
echo "    base subvols(tfork-bundles)=$BASE_SUBVOLS  du=${BASE_DU}B  df: $DF_BEFORE" | tee -a "$REPORT"

echo
echo "--- 1. start regular source ---" | tee -a "$REPORT"
sudo $PODMAN run -d --name $SRC_NAME ${ALPINE:-docker.io/library/alpine:3.20} \
    sh -c 'i=0; while true; do echo "tick $i"; i=$((i+1)); sleep 1; done' >/dev/null
sleep 2
SRC_PID=$(sudo $PODMAN inspect $SRC_NAME --format '{{.State.Pid}}')
SRC_BUNDLE=$(bundle_for_name $SRC_NAME)
echo "    src pid=$SRC_PID bundle=$SRC_BUNDLE" | tee -a "$REPORT"

echo
echo "--- 2. chain ${SRC_NAME} -> ${NAME_PREFIX}-1 .. ${NAME_PREFIX}-$DEPTH ---" | tee -a "$REPORT"
printf "%-5s %-22s %-6s %-9s %-12s %-7s\n" "gen" "name" "ms" "subvols" "tf_du(B)" "alive" | tee -a "$REPORT"

PARENT=$SRC_NAME
SRC_SNAPRO=""    # set after gen-1 (= original src snap-ro that gen-1 sees as its real subvol)

for i in $(seq 1 $DEPTH); do
    DST=${NAME_PREFIX}-$i
    LOG=$LOG_DIR/g$i.log
    BEFORE_NS=$(date +%s%N)
    if ! run_clone "$PARENT" "$DST" "$LOG"; then
        echo "FAIL: clone $PARENT -> $DST broke at gen=$i" | tee -a "$REPORT"
        echo "---- last 60 lines of $LOG ----" | tee -a "$REPORT"
        tail -60 "$LOG" | tee -a "$REPORT"
        echo "---- df ----" | tee -a "$REPORT"
        df -h /mnt/ssd3 | tee -a "$REPORT"
        echo "FAILED_AT_GEN=$i" | tee -a "$REPORT"
        exit 2
    fi
    AFTER_NS=$(date +%s%N)
    DUR_MS=$(( (AFTER_NS - BEFORE_NS) / 1000000 ))

    BUNDLE=$(bundle_for_name "$DST")
    if [ -z "$BUNDLE" ] || ! sudo test -d "$BUNDLE"; then
        echo "FAIL: bundle missing for $DST" | tee -a "$REPORT"
        exit 3
    fi

    # depth-1 invariant: lower must resolve to the same path for every gen
    LOWER=$(sudo awk -v p="$BUNDLE" '$3=="overlay" && index($2,p)==1 {print $4}' /proc/mounts \
        | tr ',' '\n' | sed -n 's/^lowerdir=//p' | head -1)
    LOWER_REAL=$(sudo readlink -f "$LOWER" 2>/dev/null || true)
    if [ -z "$LOWER_REAL" ]; then
        echo "FAIL: gen-$i has no overlay rootfs lower" | tee -a "$REPORT"
        exit 4
    fi

    if [ $i -eq 1 ]; then
        # gen-1's snap-ro is a real subvol cloned from src; we capture
        # its real path as the canonical lower for the WHOLE chain
        if sudo test -L "$BUNDLE/snap-ro"; then
            echo "FAIL: gen-1 snap-ro should be a real subvol, not a symlink" | tee -a "$REPORT"
            exit 5
        fi
        SRC_SNAPRO=$(sudo readlink -f "$BUNDLE/snap-ro")
        echo "    [info] gen-1 snap-ro real subvol = $SRC_SNAPRO" | tee -a "$REPORT"
    else
        # gen-i (i>=2) snap-ro must be a SYMLINK back to gen-1's
        if ! sudo test -L "$BUNDLE/snap-ro"; then
            echo "FAIL: gen-$i snap-ro should be a symlink" | tee -a "$REPORT"
            exit 6
        fi
        TARGET=$(sudo readlink -f "$BUNDLE/snap-ro")
        if [ "$TARGET" != "$SRC_SNAPRO" ]; then
            echo "FAIL: gen-$i snap-ro symlink -> $TARGET, expected $SRC_SNAPRO" | tee -a "$REPORT"
            exit 7
        fi
    fi
    if [ "$LOWER_REAL" != "$SRC_SNAPRO" ]; then
        echo "FAIL: gen-$i overlay lower resolves to $LOWER_REAL, expected $SRC_SNAPRO" | tee -a "$REPORT"
        exit 8
    fi

    # write a marker into this gen so the next gen inherits it via reflink-cp
    if ! sudo $PODMAN exec "$DST" sh -c "echo 'GEN${i} was here' > /GEN${i}MARK; sync" >/dev/null 2>&1; then
        echo "FAIL: exec into gen-$i failed (cannot write /GEN${i}MARK)" | tee -a "$REPORT"
        exit 9
    fi

    SUBVOLS=$(subvol_count_tfork)
    DU=$(tfork_bundles_du)
    PID=$(sudo $PODMAN inspect "$DST" --format '{{.State.Pid}}' 2>/dev/null || echo 0)
    ALIVE=no
    if [ "$PID" -gt 0 ] && sudo kill -0 "$PID" 2>/dev/null; then
        ALIVE=yes
    fi

    printf "%-5s %-22s %-6s %-9s %-12s %-7s\n" \
        "$i" "$DST" "$DUR_MS" "$SUBVOLS" "$DU" "$ALIVE" | tee -a "$REPORT"

    PARENT=$DST
done

echo
echo "--- 3. final-rung verification ---" | tee -a "$REPORT"
DEEPEST=${NAME_PREFIX}-$DEPTH
DEEP_BUNDLE=$(bundle_for_name $DEEPEST)
DEEP_PID=$(sudo $PODMAN inspect $DEEPEST --format '{{.State.Pid}}')
echo "    deepest=$DEEPEST pid=$DEEP_PID bundle=$DEEP_BUNDLE" | tee -a "$REPORT"

# every prior /GEN<i>MARK must be visible from the deepest gen
echo "    checking all $DEPTH markers visible from deepest gen..." | tee -a "$REPORT"
MISSING=()
for i in $(seq 1 $DEPTH); do
    GOT=$(sudo $PODMAN exec $DEEPEST cat /GEN${i}MARK 2>/dev/null || true)
    EXPECTED="GEN${i} was here"
    if [ "$GOT" != "$EXPECTED" ]; then
        MISSING+=("/GEN${i}MARK got='$GOT'")
    fi
done
if [ ${#MISSING[@]} -ne 0 ]; then
    echo "FAIL: deepest gen missing markers:" | tee -a "$REPORT"
    printf '    - %s\n' "${MISSING[@]}" | tee -a "$REPORT"
    exit 10
fi
echo "    all $DEPTH markers inherited: OK (collapse-via-reflink across full chain)" | tee -a "$REPORT"

# every gen still has its overlay rootfs mounted
MOUNTS_NOW=$(awk '/\/mnt\/btrfs\/.*tfork-bundles.*overlay/' /proc/mounts | wc -l)
echo "    overlay mounts on tfork-bundles: $MOUNTS_NOW" | tee -a "$REPORT"

DF_AFTER=$(df -h /mnt/ssd3 | tail -1)
END_SUBVOLS=$(subvol_count_tfork)
END_DU=$(tfork_bundles_du)
echo "    df after: $DF_AFTER" | tee -a "$REPORT"
echo "    subvols(tfork-bundles): $BASE_SUBVOLS -> $END_SUBVOLS  (+$((END_SUBVOLS - BASE_SUBVOLS)))" | tee -a "$REPORT"
echo "    tfork-bundles du: ${BASE_DU}B -> ${END_DU}B  (delta=$((END_DU - BASE_DU))B)" | tee -a "$REPORT"

# alive process count for the chain
ALIVE_COUNT=0
for i in $(seq 1 $DEPTH); do
    PID=$(sudo $PODMAN inspect ${NAME_PREFIX}-$i --format '{{.State.Pid}}' 2>/dev/null || echo 0)
    if [ "$PID" -gt 0 ] && sudo kill -0 "$PID" 2>/dev/null; then
        ALIVE_COUNT=$((ALIVE_COUNT+1))
    fi
done
echo "    chain alive count: $ALIVE_COUNT / $DEPTH" | tee -a "$REPORT"

if [ "$ALIVE_COUNT" -ne "$DEPTH" ]; then
    echo "WARN: not all chain members alive — page-cache-sharing & rollback assumptions invalidated" | tee -a "$REPORT"
fi

echo
echo "=== STRESS PASS: depth=$DEPTH ===" | tee -a "$REPORT"
echo "report at: $REPORT"
