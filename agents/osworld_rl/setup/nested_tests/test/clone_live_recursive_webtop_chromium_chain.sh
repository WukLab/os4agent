#!/bin/bash
# Linear depth-5 chain of ubuntu-webtop with wrapped-chromium running
# in the SOURCE before any clone. Targets the dead-process-remap
# regression seen on another machine:
#
#   (01.444188) Dumping path for -3 fd via self 27 [/proc/104/fdinfo]
#   (01.444201) Dumping dead process remap of 104
#   (01.444209) Error (criu/util.c:423): Can't open 104: No such file or directory
#
# Topology:
#   gen-0 wt-c-src  (chromium running)
#     └─ gen-1 wt-c-g1
#          └─ gen-2 wt-c-g2
#               └─ gen-3 wt-c-g3
#                    └─ gen-4 wt-c-g4
#                         └─ gen-5 wt-c-g5
#
# Bundles under /mnt/btrfs/podman/storage/tfork-bundles/ are
# preserved after the run so each rung's tfork.log /
# tfork-restore.log can be inspected. Driver-side clone outputs go
# under $LOG_DIR.
#
# Prereqs:
#   - btrfs storage at /mnt/btrfs/podman/storage
#   - kernel.io_uring_disabled=2  fs.nr_open=1048576
#   - in-tree podman/crun/criu/conmon binaries built
#   - localhost/ubuntu-webtop:test image present (or override IMAGE=)
#
# Usage:
#   sudo bash test/clone_live_recursive_webtop_chromium_chain.sh
#   sudo DEPTH=3 IMAGE=foo:bar bash test/clone_live_recursive_webtop_chromium_chain.sh

set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

PODMAN="${PODMAN:-$REPO_ROOT/podman/bin/podman}"
CRIU_PATH="${CRIU_PATH:-$REPO_ROOT/criu/criu}"
LIBCRIU="${LIBCRIU:-$REPO_ROOT/criu/lib/c}"
IMAGE="${IMAGE:-ghcr.io/wuklab/webtop:ubuntu-kde-osworld}"
DEPTH="${DEPTH:-5}"
BASE_PORT="${BASE_PORT:-3101}"
LOG_DIR="${LOG_DIR:-/tmp/webtop-chromium-chain}"
NAME_PREFIX="${NAME_PREFIX:-wt-c}"

rm -rf "$LOG_DIR"
mkdir -p "$LOG_DIR"

log()   { printf '\e[1;36m[%s] %s\e[0m\n' "$(date +%H:%M:%S)" "$*"; }
warn()  { printf '\e[1;33m[%s] WARN: %s\e[0m\n' "$(date +%H:%M:%S)" "$*"; }
fatal() { printf '\e[1;31m[%s] FATAL: %s\e[0m\n' "$(date +%H:%M:%S)" "$*" >&2; exit 1; }

cleanup_state() {
    set +e
    sudo "$PODMAN" rm -f $(sudo "$PODMAN" ps -aq --filter name="${NAME_PREFIX}-") 2>/dev/null
    sudo pkill -9 -f "crun.*tfork"          2>/dev/null
    sudo pkill -9 -f "criu.*restore --tfork" 2>/dev/null
    sleep 1
    sudo rm -rf /mnt/btrfs/podman/storage/tfork-bundles/* 2>/dev/null
    sudo btrfs subvolume list /mnt/btrfs/podman/storage 2>/dev/null \
        | awk '/tfork-bundles/ {print $2}' | while read -r id; do
            sudo btrfs subvolume delete --subvolid="$id" /mnt/btrfs >/dev/null 2>&1
        done
    set -e
}

# ----- Phase 0: preflight + cleanup -----
log "Phase 0: preflight"
[[ "$(sysctl -n kernel.io_uring_disabled)" == "2" ]] \
    || fatal "kernel.io_uring_disabled must be 2"
[[ -x "$PODMAN" ]]            || fatal "$PODMAN not executable"
sudo "$PODMAN" image inspect "$IMAGE" >/dev/null 2>&1 \
    || fatal "image $IMAGE not present"

if [[ "${SKIP_SETUP:-0}" == "1" ]]; then
    log "Phase 0: SKIP_SETUP=1 — assume ${NAME_PREFIX}-src is already running with chromium"
    sudo "$PODMAN" inspect "${NAME_PREFIX}-src" >/dev/null 2>&1 \
        || fatal "${NAME_PREFIX}-src not found; clear SKIP_SETUP or start it first"
else
    log "Phase 0: cleanup prior containers + tfork bundles"
    cleanup_state
fi

# ----- Phase 1: source webtop -----
SRC="${NAME_PREFIX}-src"
if [[ "${SKIP_SETUP:-0}" == "1" ]]; then
    log "Phase 1: skipped (using existing $SRC)"
else
log "Phase 1: launching $SRC on host port $BASE_PORT"
sudo "$PODMAN" run -d \
    --name "$SRC" \
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
    if sudo "$PODMAN" exec "$SRC" bash -lc 'pgrep -f plasmashell >/dev/null' 2>/dev/null; then
        log "  plasmashell up after ${i}s"
        break
    fi
    [[ $i -eq 90 ]] && fatal "plasmashell never came up in $SRC"
    sleep 1
done

log "Phase 1: KDE settle (20s)"
sleep 20
fi  # SKIP_SETUP

# ----- Phase 2: launch wrapped-chromium inside source -----
if [[ "${SKIP_SETUP:-0}" == "1" ]]; then
    log "Phase 2: skipped (assuming chromium already running in $SRC)"
    n=$(sudo "$PODMAN" exec "$SRC" \
        bash -lc 'pgrep -fc chromium 2>/dev/null || echo 0' 2>/dev/null \
        | tr -d '[:space:]')
    n="${n:-0}"
    [[ "$n" -ge 2 ]] || fatal "chromium not running in $SRC (count=$n); clear SKIP_SETUP or launch chromium first"
    log "  chromium up: $n processes"
else
log "Phase 2: launching /usr/local/bin/wrapped-chromium inside $SRC"
sudo "$PODMAN" exec -d -u abc -w /config \
    -e DISPLAY=:1 -e HOME=/config -e USER=abc \
    "$SRC" sh -c 'setsid nohup /usr/local/bin/wrapped-chromium >/dev/null 2>&1 </dev/null &' \
    > "$LOG_DIR/chromium-launch.log" 2>&1 || true   # ported: detach stdio, else CRIU sees conmon's exec sockets ("External socket is used")

log "Phase 2: waiting for chromium processes (need >=2)"
chromium_count=0
for i in $(seq 1 60); do
    chromium_count=$(sudo "$PODMAN" exec "$SRC" \
        bash -lc 'pgrep -fc chromium 2>/dev/null || echo 0' 2>/dev/null \
        | tr -d '[:space:]')
    chromium_count="${chromium_count:-0}"
    if [[ "$chromium_count" -ge 2 ]]; then
        log "  chromium up: $chromium_count processes after ${i}s"
        break
    fi
    [[ $i -eq 60 ]] && fatal "chromium never spawned (count=$chromium_count); see $LOG_DIR/chromium-launch.log"
    sleep 1
done

log "Phase 2: chromium settle (10s)"
sleep 10

fi  # SKIP_SETUP

log "Phase 2: snapshot of source process tree (for reference)"
sudo "$PODMAN" exec "$SRC" \
    bash -lc 'ps -eo pid,ppid,user,comm | head -200' \
    > "$LOG_DIR/src-ps-pre-clone.log" 2>&1 || true
sudo "$PODMAN" exec "$SRC" \
    bash -lc 'pgrep -af chromium' \
    > "$LOG_DIR/src-chromium-pre-clone.log" 2>&1 || true

# ----- Helpers -----
http_check() {
    local name="$1" port code
    port=$(sudo "$PODMAN" port "$name" 3001/tcp 2>/dev/null | awk -F: '{print $2}' | head -1)
    [[ -z "$port" ]] && { warn "  $name: no port mapping"; return 0; }
    code=$(curl -k -s -m 5 -o /dev/null -w '%{http_code}' \
        -u admin:changeme "https://localhost:$port/" 2>/dev/null || echo FAIL)
    log "  $name port=$port http=$code"
}

plasmashell_check() {
    local name="$1"
    if ! sudo "$PODMAN" exec "$name" bash -lc 'pgrep -f plasmashell >/dev/null' 2>/dev/null; then
        fatal "plasmashell not running in $name"
    fi
    log "  $name plasmashell: alive"
}

chromium_check() {
    local name="$1" n
    n=$(sudo "$PODMAN" exec "$name" \
        bash -lc 'pgrep -fc chromium 2>/dev/null || echo 0' 2>/dev/null \
        | tr -d '[:space:]')
    n="${n:-0}"
    if [[ "$n" -lt 1 ]]; then
        warn "  $name chromium: NOT alive (count=$n)"
    else
        log "  $name chromium: alive (count=$n)"
    fi
}

dump_failure_artefacts() {
    local dst="$1"
    log "  --- tail $LOG_DIR/clone-$dst.log ---"
    tail -60 "$LOG_DIR/clone-$dst.log" 2>/dev/null | sed 's/^/    /' || true
    log "  --- search bundles for tfork.log / tfork-restore.log ---"
    find /mnt/btrfs/podman/storage/tfork-bundles -maxdepth 4 \
        \( -name 'tfork.log' -o -name 'tfork-restore.log' \) 2>/dev/null \
        > "$LOG_DIR/bundle-logs-$dst.list" || true
    sed 's/^/    /' "$LOG_DIR/bundle-logs-$dst.list" || true
    if [[ -s "$LOG_DIR/bundle-logs-$dst.list" ]]; then
        local newest
        newest=$(xargs -d '\n' -I{} stat -c '%Y {}' "$LOG_DIR/bundle-logs-$dst.list" 2>/dev/null \
            | sort -n | tail -1 | awk '{print $2}')
        if [[ -n "$newest" ]]; then
            log "  --- tail $newest (last 80 lines) ---"
            tail -80 "$newest" 2>/dev/null | sed 's/^/    /' || true
        fi
    fi
}

clone_live() {
    local src="$1" dst="$2" rc=0
    log "  cloning $src -> $dst"
    sudo env PATH="$CRIU_PATH:$PATH" LD_LIBRARY_PATH="$LIBCRIU" \
        "$PODMAN" container clone --live --copies=1 --persistent=async \
        --name "$dst" "$src" \
        > "$LOG_DIR/clone-$dst.log" 2>&1 || rc=$?
    if [[ $rc -ne 0 ]]; then
        log "  CLONE FAILED rc=$rc for $src -> $dst"
        dump_failure_artefacts "$dst"
        fatal "clone $src -> $dst failed; logs $LOG_DIR/, bundles preserved"
    fi
}

# ----- Phase 3: linear chain -----
log ""
log "Phase 3: linear chain depth=$DEPTH"
PREV="$SRC"
for i in $(seq 1 "$DEPTH"); do
    NEXT="${NAME_PREFIX}-g${i}"
    log ""
    log "Phase 3.$i: gen-$i  ($PREV -> $NEXT)"
    plasmashell_check "$PREV"
    chromium_check    "$PREV"
    clone_live        "$PREV" "$NEXT"
    plasmashell_check "$NEXT"
    chromium_check    "$NEXT"
    http_check        "$NEXT"
    PREV="$NEXT"
    sleep "${RUNG_SETTLE:-0}"   # ported: optional settle between rungs (restored chromium may have unread netlink data)
done

# ----- Phase 4: summary -----
log ""
log "=== SUMMARY ==="
total=$(sudo "$PODMAN" ps --filter name="${NAME_PREFIX}-" -q | wc -l)
log "  webtop containers running : $total (expected $((DEPTH + 1)))"
sudo "$PODMAN" ps --filter name="${NAME_PREFIX}-" \
    --format '  {{.Names}}  state={{.Status}}  ports={{.Ports}}'
log ""
log "  driver logs   : $LOG_DIR/"
log "  bundle logs   : /mnt/btrfs/podman/storage/tfork-bundles/"
log "  src ps snapshot: $LOG_DIR/src-ps-pre-clone.log"
log "=== PASS ==="
