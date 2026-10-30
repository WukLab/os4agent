#!/bin/bash
# Two-epoch replay of the tree-closed lazy cache at depth 8 under the live loop's 40 GiB budget, no model: the last two
# epochs of the live GRPO loop, 16 tasks x 8, --parallel 8, overlay 0, with the recorded model latency
# (--replay-latency 1):
#   e0  replay traces/team16_plazy_e4 into an empty cache                -> traces/tree8_e0
#   e1  replay traces/team16_plazy_e5 through it (one GRPO update apart)  -> traces/tree8_e1
# Cache: --prefix-depth 8 --prefix-tree (save under a cached parent or one being saved, evict leaves only, lru) --prefix-lazy-start (no
# group-start copies) --prefix-admit-visits 2, shared clones at a miss, --prefix-mem-budget-gib ${BUDGET:-40},
# --clone-copies-limit ${CLONE_LIMIT:-16} (copies being cloned at once, over group forks, saves and materializations).
# Each epoch: equiv_check.py against its recording, tree_check.py; then pmem_report.py, timeline_breakdown.py; the
# cache's index and visit counts are kept in traces/tree8_cache_final/, the snapshots removed.
#   bash run_tree8_replay.sh
set -uo pipefail
cd "$(dirname "$0")"
REPO="$(cd ../.. && pwd)"; C=$PWD/traces/tree8_cache; B=${BUDGET:-40}; L=${CLONE_LIMIT:-16}
PT="sudo -n env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf $REPO/podman-tfork.sh"
uncache() {
    [ -f "$1/index.json" ] && sudo -n venv/bin/python -I -c "import json,sys; [print(e.get('mem') or e.get('clone')) for e in json.load(open(sys.argv[1])).values() if e and (e.get('mem') or e.get('clone'))]" "$1/index.json" \
        | xargs -r $PT rm -f -t 0 >/dev/null 2>&1
    sudo -n rm -rf "$1"
}
epoch() {   # epoch, recording
    d=traces/tree8_e$1
    sudo -n rm -rf $d
    echo "$(date +%T) start $d (replay $2)"
    sudo -n env DOUBAO_API_URL=http://127.0.0.1:1/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system tfork \
        --tasks grpo_batch16_team.json --os4agent $REPO --storage-conf /mnt/data/btrfs/podman/storage.conf --result-dir $d \
        --rollouts 8 --parallel 8 --replay $2 --replay-latency 1 --overlay-rootfs 0 --prefix-cache $C --prefix-depth 8 \
        --prefix-mem --prefix-lazy --prefix-lazy-start --prefix-tree --prefix-admit-visits 2 \
        --prefix-mem-budget-gib $B --prefix-policy lru --clone-copies-limit $L --epoch $1 > $d.log 2>&1 || echo "osw_run exited $?"
    sudo -n chown -R "$(id -u):$(id -g)" $d $d.log $C
    { echo "== $d (replay $2, budget $B GiB, clone limit $L) $(date +%T)"
      venv/bin/python -I equiv_check.py $d $2 | grep -vE "^  (chrome|gimp|libreoffice)"
      venv/bin/python -I tree_check.py $d $C; } > $d.summary.txt 2>&1
    cat $d.summary.txt
}
[ "$($PT ps -aq | wc -l)" = 0 ] || { echo "containers are running: not starting"; exit 1; }
uncache $C
epoch 0 traces/team16_plazy_e4
epoch 1 traces/team16_plazy_e5
echo "=== performance (split_e4_control: the same recording as tree8_e0, no cache; live_e5: depth 2, plain lru, 40 GiB)"
venv/bin/python -I pmem_report.py traces/split_e4_control traces/tree8_e0 traces/tree8_e1 traces/team16_plazy_e5 --csv traces/tree8_report.csv
venv/bin/python -I timeline_breakdown.py traces/split_e4_control=split_e4_control traces/tree8_e0=tree8_e0 traces/tree8_e1=tree8_e1 \
    traces/team16_plazy_e5=live_e5 --csv traces/tree8_timeline.csv | grep -vE "^  slot"
rm -rf traces/tree8_cache_final && mkdir -p traces/tree8_cache_final && cp $C/index.json $C/visits.json traces/tree8_cache_final/
uncache $C
echo "$(date +%T) all done; containers left: $($PT ps -aq | wc -l)"
