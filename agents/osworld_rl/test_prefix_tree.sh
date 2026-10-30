#!/bin/bash
# Smoke test of the tree-closed lazy cache: --prefix-tree (save only under a cached parent, evict leaves only),
# --prefix-lazy-start (a group with a cached after-setup state forks no copies; one fork per rollout, at its first miss),
# shared clones (rollouts that miss together share one --copies=k clone), --prefix-admit-visits 2, depth 8, on replays
# of traces/smoke_live (calc + gimp, 2 rollouts each, no model), two epochs, a budget small enough to force evictions.
# Each epoch: equiv_check.py against the recording; tree_check.py (the tree invariant, forks per rollout, evictions).
#   bash test_prefix_tree.sh [budget GiB, default 2.5]
set -uo pipefail
cd "$(dirname "$0")"
REPO="$(cd ../.. && pwd)"; B=${1:-2.5}; C=$PWD/traces/test_ptree_cache
PT="sudo -n env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf $REPO/podman-tfork.sh"
uncache() {
    [ -f "$1/index.json" ] && sudo -n venv/bin/python -I -c "import json,sys; [print(e.get('mem') or e.get('clone')) for e in json.load(open(sys.argv[1])).values() if e and (e.get('mem') or e.get('clone'))]" "$1/index.json" \
        | xargs -r $PT rm -f -t 0 >/dev/null 2>&1
    sudo -n rm -rf "$1"
}
epoch() {   # epoch
    d=traces/test_ptree_e$1
    sudo -n rm -rf $d
    sudo -n env DOUBAO_API_URL=http://127.0.0.1:1/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system tfork \
        --tasks smoke_noweb2.json --os4agent $REPO --storage-conf /mnt/data/btrfs/podman/storage.conf --result-dir $d \
        --rollouts 2 --parallel 2 --replay traces/smoke_live --overlay-rootfs 0 --prefix-cache $C --prefix-depth 8 \
        --prefix-mem --prefix-lazy --prefix-lazy-start --prefix-tree --prefix-admit-visits 2 \
        --prefix-mem-budget-gib $B --prefix-policy lru --epoch $1 > $d.log 2>&1 || echo "osw_run exited $?"
    sudo -n chown -R "$(id -u):$(id -g)" $d $d.log $C
    { echo "== epoch $1 (budget $B GiB) $(date +%T)"
      venv/bin/python -I equiv_check.py $d traces/smoke_live | grep -E "prefix cache|rewards equal|rollouts .* errors|obs"
      venv/bin/python -I tree_check.py $d $C; } > $d.summary.txt 2>&1
    cat $d.summary.txt
}
uncache $C
epoch 0
epoch 1
uncache $C
echo "containers left: $($PT ps -aq | wc -l)"
