#!/bin/bash
# Rebuild CRIU (binary + libcriu), crun and podman in place after a source update (e.g. main's 723818076, which adds
# `podman container tfork-restore`), with at most JOBS (default 8) parallel jobs. Only the make steps of
# criu/crun/podman build.sh: no apt install, no reconfigure, and no kernel module reload (run criu/build.sh for that
# when criu's modules change). Run as root with no tfork containers running.
#   sudo [JOBS=8] bash setup/rebuild_tfork_stack.sh
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"; JOBS=${JOBS:-8}
cd "$REPO/criu" && echo "$(date +%T) criu" && make -j"$JOBS" >/dev/null && make -j"$JOBS" lib >/dev/null
cd "$REPO/crun" && echo "$(date +%T) crun" && make -j"$JOBS" >/dev/null
cd "$REPO/podman" && echo "$(date +%T) podman" && PATH=/usr/local/go/bin:$PATH make GOFLAGS="-p=$JOBS" podman >/dev/null
cd "$REPO"
P=(env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf
   CONTAINERS_CONF="$REPO/agents/osworld_rl/containers-os4agent.conf" "$REPO/podman-tfork.sh")
"${P[@]}" container tfork-restore --help | grep -q -- "--name" || { echo "podman has no tfork-restore"; exit 1; }
"${P[@]}" container clone --help | grep -q -- "--persistent" || { echo "podman clone has no --persistent"; exit 1; }
ls -l --time-style=+%T criu/criu/criu criu/lib/c/libcriu.so* crun/crun podman/bin/podman | awk '{print $6, $7}'
echo "$(date +%T) done: tfork-restore available"
