#!/bin/bash
# Kill WebArena shop stacks left running in /libpod_parent/libpod-<id> cgroups that podman no longer knows (e.g. tfork
# copies of a clone in progress when a run was stopped: never registered, so neither podman nor cleanup_replay.sh sees
# them). A cgroup is killed only if podman has no container with its id and every process in it is a known part of
# the shop image; then its now-empty cgroup is removed. DRY=1 only lists.
#   sudo [DRY=1] bash setup/kill_orphan_stacks.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")/../../.." && pwd)"
# PODMAN_TFORK_SKIP_SYSCTL: only `ps` runs, so this works while io_uring is on for AgentENV
PT=(env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf
    CONTAINERS_CONF="$HERE/agents/webarena_rl/containers-os4agent.conf" "$HERE/podman-tfork.sh")
OK=" mysqld nginx php-fpm redis-server java chromium chrome_crashpad socat supervisord mailcatcher crond "
known=$("${PT[@]}" ps -a --no-trunc --format '{{.ID}}') || { echo "podman ps failed: not touching anything"; exit 1; }
echo "podman knows $(grep -c . <<< "$known") containers"
targets=()
for c in /sys/fs/cgroup/libpod_parent/libpod-*/; do
    id=${c%/}; id=${id##*/libpod-}
    pids=$(find "$c" -name cgroup.procs -exec cat {} + 2>/dev/null)
    [ -n "$pids" ] || continue
    if grep -qx "$id" <<< "$known"; then echo "skip ${id:0:12}: podman knows it"; continue; fi
    comms=$(for p in $pids; do cat /proc/$p/comm 2>/dev/null; done | sort | uniq -c | tr -s ' ' | tr '\n' ',')
    bad=$(for p in $pids; do cm=$(cat /proc/$p/comm 2>/dev/null) && [[ "$OK" != *" $cm "* ]] && echo "$cm"; done | sort -u)
    if [ -n "$bad" ]; then echo "skip ${id:0:12}: unexpected processes: $bad"; continue; fi
    host=$(nsenter -t "$(head -1 <<< "$pids")" -u hostname 2>/dev/null)
    echo "${id:0:12} host $host: $(wc -w <<< "$pids") procs ($comms) $(( $(cat "$c/memory.current") >> 20 )) MiB"
    targets+=("$c")
done
echo "${#targets[@]} orphan stacks"
[ "${DRY:-0}" = 1 ] && exit 0
for c in "${targets[@]}"; do
    for _ in $(seq 10); do   # SIGKILL everything at once; repeat in case a supervisor respawned a child in between
        pids=$(find "$c" -name cgroup.procs -exec cat {} + 2>/dev/null)
        [ -n "$pids" ] || break
        kill -KILL $pids 2>/dev/null
        sleep 1
    done
    find "$c" -depth -type d -exec rmdir {} \; 2>/dev/null
    [ -d "$c" ] && echo "still there: $c ($(find "$c" -name cgroup.procs -exec cat {} + | wc -l) procs)"
done
echo "$(date +%T) done; libpod cgroups with processes left: $(for c in /sys/fs/cgroup/libpod_parent/libpod-*/; do \
    [ -n "$(find "$c" -name cgroup.procs -exec cat {} + 2>/dev/null)" ] && echo; done | wc -l)"
