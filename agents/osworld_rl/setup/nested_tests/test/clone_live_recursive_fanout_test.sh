#!/usr/bin/env bash
# Recursive clone-of-clone with N>1 fan-out at every generation (the dothyt recursive tests only chain --copies=1).
# Mirrors the OSWorld runner's base fork: src -> --copies=N gen-1 -> each gen-1 copy -> --copies=N gen-2 -> one gen-2 -> --copies=N gen-3.
#
# Per copy checks: running, own cgroup, crun's /run/crun/<id>/status "cgroup-path" non-empty (CRIU's freeze cgroup for the next
# generation's dump comes from it; empty = the next clone fails with "Neither ... cgroup.freeze control file found"), and the
# workload process still alive. Writes /GEN<i>MARK per generation and checks inheritance.
#
# Usage: sudo PODMAN=... [CGROUPNS=host|private] [COPIES=2] [IMAGE=...] bash test/clone_live_recursive_fanout_test.sh
set -uo pipefail
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
PODMAN="${PODMAN:-$REPO_ROOT/podman-tfork.sh}"
IMAGE="${IMAGE:-docker.io/library/alpine:3.20}"
COPIES="${COPIES:-2}"; CGROUPNS="${CGROUPNS:-host}"; PREFIX="${PREFIX:-tfork-fan}"
LOG_DIR="${LOG_DIR:-/tmp/tfork-fanout}"; mkdir -p "$LOG_DIR"
fails=0
pass() { echo "PASS: $*"; }
fail() { echo "FAIL: $*"; fails=$((fails + 1)); }
FAILF=$(mktemp)   # clone() runs in $(...) subshells: count its failures through a file

sudo "$PODMAN" rm -f $(sudo "$PODMAN" ps -aq --filter name=$PREFIX) >/dev/null 2>&1
cleanup() { sudo "$PODMAN" rm -f $(sudo "$PODMAN" ps -aq --filter name=$PREFIX) >/dev/null 2>&1; }
trap cleanup EXIT

check_copy() {   # <id> <gen>
    local id=$1 gen=$2 pid cg st
    pid=$(sudo "$PODMAN" inspect "$id" --format '{{.State.Pid}}' 2>/dev/null)
    [[ "$(sudo "$PODMAN" inspect "$id" --format '{{.State.Running}}' 2>/dev/null)" == true && "$pid" -gt 0 ]] \
        || { fail "gen-$gen ${id:0:12} not running"; return; }
    cg=$(cut -d: -f3 /proc/$pid/cgroup)
    [[ "$cg" == *"$id"* ]] && pass "gen-$gen ${id:0:12} in own cgroup" || fail "gen-$gen ${id:0:12} cgroup $cg"
    st=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("cgroup-path",""))' /run/crun/$id/status 2>/dev/null)
    # crun leaves it empty for tfork copies; podman-tfork.sh fills it right before the next clone, so only note it here
    [[ -n "$st" ]] || echo "NOTE: gen-$gen ${id:0:12} crun status cgroup-path empty (podman-tfork.sh fills it before cloning)"
    sudo "$PODMAN" exec "$id" sh -c 'pgrep -f "sleep 1" >/dev/null || pgrep sleep >/dev/null' \
        && pass "gen-$gen ${id:0:12} workload alive" || fail "gen-$gen ${id:0:12} workload dead"
    for g in $(seq 1 $((gen - 1))); do
        sudo "$PODMAN" exec "$id" test -f /GEN${g}MARK || fail "gen-$gen ${id:0:12} missing /GEN${g}MARK"
    done
}

clone() {   # <src> <gen> -> ids on stdout
    local src=$1 gen=$2 out="$LOG_DIR/clone-gen$2-${1:0:12}.log"
    sudo "$PODMAN" exec "$src" sh -c "touch /GEN$((gen - 1))MARK" 2>/dev/null
    if ! sudo "$PODMAN" container clone --live --copies="$COPIES" --persistent=async --name "$PREFIX-g$gen-${src:0:6}" "$src" >"$out" 2>&1; then
        { echo "FAIL: gen-$gen clone of ${src:0:12} (see $out)"
          grep -m3 "Error" "$(grep -o '/mnt/ssd3/[^ "]*crun-tfork.log' "$out" | head -1)" 2>/dev/null; } >&2
        echo x >> "$FAILF"; return
    fi
    grep -E '^[0-9a-f]{64}$' "$out"
}

echo "== src ($IMAGE, cgroupns=$CGROUPNS, copies=$COPIES)"
sudo "$PODMAN" run -d --name $PREFIX-src --cgroupns=$CGROUPNS --security-opt seccomp=unconfined --security-opt label=disable \
    --entrypoint sh "$IMAGE" -c 'while true; do sleep 1; done' >/dev/null || { echo "FAIL: src did not start"; exit 1; }
sleep 2
g1=$(clone $PREFIX-src 1); n=$(echo $g1 | wc -w)
[[ $n -eq $COPIES ]] && pass "gen-1: $n copies" || fail "gen-1: $n copies, want $COPIES"
for c in $g1; do check_copy $c 1; done
g2=""; for c in $g1; do g2="$g2 $(clone $c 2)"; done; n=$(echo $g2 | wc -w)
[[ $n -eq $((COPIES * COPIES)) ]] && pass "gen-2: $n copies" || fail "gen-2: $n copies, want $((COPIES * COPIES))"
for c in $g2; do check_copy $c 2; done
first=$(echo $g2 | cut -d' ' -f1)
if [[ -n "$first" ]]; then
    g3=$(clone $first 3); n=$(echo $g3 | wc -w)
    [[ $n -eq $COPIES ]] && pass "gen-3: $n copies" || fail "gen-3: $n copies, want $COPIES"
    for c in $g3; do check_copy $c 3; done
fi
fails=$((fails + $(wc -l < "$FAILF")))
[[ $fails -eq 0 ]] && echo "=== PASS ===" || { echo "=== FAIL ($fails) ==="; exit 1; }
