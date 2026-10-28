#!/bin/bash
# Replay one recording on several systems back to back (same tasks, same settings), then leave the host idle.
#   ./compare.sh <recording-dir> <tasks.json> <out-prefix> [systems...] [-- extra osw_run.py args]
#   ./compare.sh traces/rec32v2_tfork grpo_batch32v2.json traces/replay32 tfork criu aenv -- --parallel 8
# Writes <out-prefix>_<system>/ and <out-prefix>_<system>.log per system.
set -u
cd "$(dirname "$0")"
REC=$(realpath "$1"); TASKS=$(realpath "$2"); PREFIX=$3; shift 3
SYSTEMS=(); while [ $# -gt 0 ] && [ "$1" != "--" ]; do SYSTEMS+=("$1"); shift; done
[ "${1:-}" = "--" ] && shift
[ ${#SYSTEMS[@]} -gt 0 ] || SYSTEMS=(tfork criu aenv)

# host paths: override to match osw_run.py's --os4agent / --storage-conf / --aenv-key
OS4AGENT=${OS4AGENT:-/mnt/ssd2/os4agent}
STORAGE_CONF=${STORAGE_CONF:-/mnt/btrfs/podman/storage.conf}
AENV_KEY=${AENV_KEY:-/mnt/ssd2/aenv/env/secrets/api-key}
P="sudo env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=$STORAGE_CONF CONTAINERS_CONF=$PWD/containers-os4agent.conf $OS4AGENT/podman-tfork.sh"
KEY=$(sudo cat "$AENV_KEY" 2>/dev/null)

cleanup() {
  $P ps -a --format "{{.Names}}" | xargs -r -n 20 $P rm -f >/dev/null 2>&1
  curl -fs -H "X-API-Key: $KEY" http://127.0.0.1:8000/sandboxes 2>/dev/null |
    python3 -c "import json, sys; [print(s['sandboxID']) for s in json.load(sys.stdin)]" 2>/dev/null |
    while read -r sb; do curl -fs -X DELETE -H "X-API-Key: $KEY" "http://127.0.0.1:8000/sandboxes/$sb" >/dev/null; done
}

for sys in "${SYSTEMS[@]}"; do
  out="${PREFIX}_${sys}"
  sudo rm -rf "$out"
  echo "$(date +%T) $sys -> $out"
  sudo env DOUBAO_API_URL=http://127.0.0.1:1/v1 venv/bin/python osw_run.py --system "$sys" --tasks "$TASKS" \
    --replay "$REC" --result-dir "$out" --os4agent "$OS4AGENT" --storage-conf "$STORAGE_CONF" --aenv-key "$AENV_KEY" \
    "$@" > "$out.log" 2>&1   # osw_run.py switches io_uring / aenv-server itself
  cleanup
  sudo chown -R "$(id -u):$(id -g)" "$out" "$out.log"
done

sudo docker stop aenv-server >/dev/null 2>&1
echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled >/dev/null
echo "$(date +%T) done"
