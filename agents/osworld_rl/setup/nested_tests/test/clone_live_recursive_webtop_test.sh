#!/bin/bash
# Recursive clone-of-clone smoke for the ubuntu-webtop image.
#
# Topology (1 + 1 + 2 + 4 = 8 KDE-Plasma webtops at peak):
#
#   gen-0  webtop-src
#     └─ gen-1  webtop-g1
#          ├─ gen-2  webtop-g2-0
#          │    ├─ gen-3  webtop-g3-0
#          │    └─ gen-3  webtop-g3-1
#          └─ gen-2  webtop-g2-1
#               ├─ gen-3  webtop-g3-2
#               └─ gen-3  webtop-g3-3
#
# Differs from `webtop_e2e_test.sh` (flat fan-out from src) and
# `clone_live_recursive_clone_test.sh` (alpine-based recursion):
# this is webtop *and* recursive, exercising the cgroupns + overlay
# + reflink-cp paths under a real KDE workload.
#
# Between each rung we podman-exec `pgrep -f plasmashell` against the
# *source* of that rung's clone, so a regression that kills
# plasmashell on the parent (e.g. dump-side fd handling) surfaces
# before the next rung's clone is attempted instead of as a generic
# clone failure.
#
# Prereqs (same as webtop_e2e_test.sh):
#   - btrfs storage at /mnt/btrfs/podman/storage
#   - kernel.io_uring_disabled=2  fs.nr_open=1048576
#   - in-tree podman/crun/criu/conmon binaries built
#   - localhost/ubuntu-webtop:test image present
#   - /usr/local/sbin/criu symlink + libcriu in ld.so.conf.d
#     (or run via ./podman-tfork.sh)
#
# Usage:
#   sudo bash test/clone_live_recursive_webtop_test.sh

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

PODMAN="${PODMAN:-$REPO_ROOT/podman/bin/podman}"
CRIU_PATH="${CRIU_PATH:-$REPO_ROOT/criu/criu}"
LIBCRIU="${LIBCRIU:-$REPO_ROOT/criu/lib/c}"
IMAGE="${IMAGE:-ghcr.io/wuklab/webtop:ubuntu-kde-osworld}"
BASE_PORT="${BASE_PORT:-3101}"
LOG_DIR="${LOG_DIR:-/tmp/ubuntu_webtop_recursive}"

mkdir -p "$LOG_DIR"

log()   { printf '\e[1;36m[%s] %s\e[0m\n' "$(date +%H:%M:%S)" "$*"; }
fatal() { printf '\e[1;31m[%s] FATAL: %s\e[0m\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

# Sanity gates
log "Phase 0: sanity gates"
[[ "$(sysctl -n kernel.io_uring_disabled)" == "2" ]] \
    || fatal "kernel.io_uring_disabled must be 2"
[[ -x "$PODMAN" ]]            || fatal "$PODMAN not executable"
sudo "$PODMAN" image inspect "$IMAGE" >/dev/null 2>&1 \
    || fatal "image $IMAGE not present"

# Cleanup prior state
log "Phase 0: cleanup prior containers + tfork bundles"
sudo "$PODMAN" rm -f $(sudo "$PODMAN" ps -aq --filter name=webtop) 2>/dev/null || true
sudo pkill -9 -f "crun.*tfork" 2>/dev/null || true
sudo pkill -9 -f "criu.*restore --tfork" 2>/dev/null || true
sleep 2
sudo rm -rf /mnt/btrfs/podman/storage/tfork-bundles/* 2>/dev/null || true
sudo btrfs subvolume list /mnt/btrfs/podman/storage 2>/dev/null \
    | awk '/tfork-bundles/ {print $2}' | while read -r id; do
        sudo btrfs subvolume delete --subvolid="$id" /mnt/btrfs >/dev/null 2>&1 || true
    done

http_check() {
    local name="$1"
    local port
    port=$(sudo "$PODMAN" port "$name" 3001/tcp | awk -F: '{print $2}' | head -1)
    [[ -n "$port" ]] || { log "  $name: no port mapping"; return 1; }
    local code
    code=$(curl -k -s -m 5 -o /dev/null -w '%{http_code}' \
        -u admin:changeme "https://localhost:$port/" 2>/dev/null || echo FAIL)
    log "  $name port=$port http=$code"
    [[ "$code" == "200" ]]
}

# Sanity check that plasmashell is still alive in `name`. Used between
# rungs so a parent that died from a prior dump surfaces here, not as
# a downstream clone failure.
plasmashell_check() {
    local name="$1"
    if ! sudo "$PODMAN" exec "$name" bash -lc 'pgrep -f plasmashell >/dev/null' 2>/dev/null; then
        fatal "plasmashell not running in $name (prior rung corrupted parent state)"
    fi
    log "  $name plasmashell: alive"
}

clone_live() {
    local src="$1" dst="$2"
    log "  cloning $src -> $dst"
    # libcriu/crun lookup: the system libcriu lacks tfork, so crun's
    # dlopen needs LD_LIBRARY_PATH at the in-tree build. PATH lets
    # libcriu's swrk fork resolve the in-tree criu binary too.
    sudo env PATH="$CRIU_PATH:$PATH" LD_LIBRARY_PATH="$LIBCRIU" \
        "$PODMAN" container clone --live --copies=1 --persistent=async \
        --name "$dst" "$src" \
        > "$LOG_DIR/clone-$dst.log" 2>&1 \
        || fatal "clone $src -> $dst failed; see $LOG_DIR/clone-$dst.log"
}

# 1. Source
log "Phase 1: launch webtop-src on port $BASE_PORT"
sudo "$PODMAN" run -d \
    --name webtop-src \
    --log-driver=k8s-file \
    --security-opt seccomp=unconfined \
    --security-opt apparmor=unconfined \
    --shm-size=2g \
    --tmpfs /config:size=512m \
    --tmpfs /tmp:size=1g \
    --tmpfs /run:size=256m \
    -e PUID=1000 -e PGID=1000 -e TZ=Etc/UTC \
    -e CUSTOM_USER=admin -e PASSWORD=changeme \
    -p "${BASE_PORT}:3001" \
    "$IMAGE" > "$LOG_DIR/run-src.log"

log "Phase 1: waiting for plasmashell"
for i in $(seq 1 90); do
    if sudo "$PODMAN" exec webtop-src bash -lc 'pgrep -f plasmashell >/dev/null' 2>/dev/null; then
        log "Phase 1: plasmashell up after ${i}s"
        break
    fi
    [[ $i -eq 90 ]] && fatal "plasmashell never came up"
    sleep 1
done
sleep 20  # KDE socket/scheduler queues need time to drain (see memsnap_webtop_fanout.sh)
http_check webtop-src || fatal "webtop-src not serving"

# 2. gen-1
log "Phase 2: gen-1 (webtop-src -> webtop-g1)"
clone_live webtop-src webtop-g1
http_check webtop-g1 || fatal "webtop-g1 not serving"

# Gate before gen-2: did the gen-1 dump leave plasmashell intact on
# the source? (Inserted to surface a regression seen on a different
# machine, where the gen-1 dump killed src-side plasmashell and the
# gen-2 clone then failed for the wrong reason.)
plasmashell_check webtop-src
plasmashell_check webtop-g1

# 3. gen-2 (2 clones of gen-1)
log "Phase 3: gen-2 (webtop-g1 -> webtop-g2-0, webtop-g2-1)"
clone_live webtop-g1 webtop-g2-0
clone_live webtop-g1 webtop-g2-1
http_check webtop-g2-0 || fatal "webtop-g2-0 not serving"
http_check webtop-g2-1 || fatal "webtop-g2-1 not serving"

plasmashell_check webtop-g2-0
plasmashell_check webtop-g2-1

# 4. gen-3 (2 clones from each gen-2 = 4 total)
log "Phase 4: gen-3 (4 clones across gen-2)"
clone_live webtop-g2-0 webtop-g3-0
clone_live webtop-g2-0 webtop-g3-1
clone_live webtop-g2-1 webtop-g3-2
clone_live webtop-g2-1 webtop-g3-3
for c in webtop-g3-0 webtop-g3-1 webtop-g3-2 webtop-g3-3; do
    http_check "$c" || fatal "$c not serving"
done

plasmashell_check webtop-g3-0
plasmashell_check webtop-g3-1
plasmashell_check webtop-g3-2
plasmashell_check webtop-g3-3

# 5. Final tally
log ""
log "=== SUMMARY ==="
total_running=$(sudo "$PODMAN" ps --filter name=webtop -q | wc -l)
log "  webtop containers running : $total_running (expected 8)"
log "  topology: src + g1 + 2 g2 + 4 g3 = 1+1+2+4 = 8"
sudo "$PODMAN" ps --filter name=webtop \
    --format '  {{.Names}}  state={{.Status}}  ports={{.Ports}}'
log "=== PASS ==="
