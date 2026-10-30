#!/bin/bash
# After a reboot (or a new kernel): rebuild os4agent's 4 CRIU kernel modules for the running kernel and insmod them
# (criu/build.sh, after `make clean` so no .ko built for the old kernel survives), then set the runtime-only tfork
# sysctls (build_tfork.sh stage 6) and check that podman-tfork's preflight passes.
#   bash agents/webarena_rl/setup/after_reboot.sh      (from the os4agent checkout; needs sudo -n)
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
LOG=/mnt/data/ssd4/yutong/tfork_build/after_reboot_$(uname -r)
mkdir -p "$LOG"
cd "$REPO/criu"
for m in kernel_module/*/; do (cd "$m" && make clean > /dev/null); done
echo "$(date +%T) criu/build.sh for $(uname -r) (log $LOG/criu_build.log) ..."
sudo -n ./build.sh > "$LOG/criu_build.log" 2>&1 || { tail -30 "$LOG/criu_build.log"; exit 1; }
lsmod | grep -E '^(criu_capbypass|pkey_state|reparent_task|vma_cherrypick) '
for m in kernel_module/*/*.ko; do echo "$m: $(modinfo -F vermagic "$m" | cut -d' ' -f1)"; done
# fs.aio-max-nr: every environment's MySQL (InnoDB native AIO) holds ~4,300 AIO events; the default 65536 fails tfork
# restores of a 36-environment wave; all 32 groups at once is up to 288 environments, ~1.24M (CRIU restorer: io_setup EAGAIN, "Ring setup failed with -11")
sudo -n sysctl -w kernel.io_uring_disabled=2 fs.inotify.max_user_instances=524288 kernel.apparmor_restrict_unprivileged_unconfined=0 fs.aio-max-nr=4194304
sudo -n env CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf \
    CONTAINERS_CONF="$REPO/agents/webarena_rl/containers-os4agent.conf" "$REPO/podman-tfork.sh" ps -a > /dev/null
echo "$(date +%T) ok: modules loaded, sysctls set, podman-tfork preflight passes"
