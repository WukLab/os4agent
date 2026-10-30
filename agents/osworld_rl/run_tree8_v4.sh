#!/bin/bash
# Depth-8 tree cache, version 4 (v3 + eviction by the run's schedule: done groups' entries first, then pending
# groups' latest-scheduled first, running ones last; hits pin before they look), two-epoch replay from a cold cache, no model (recorded model
# latency, --replay-latency 1), 16 tasks x 8, --parallel 8, overlay 0, --clone-copies-limit 16, 40 GiB:
#   e0   replay traces/team16_plazy_e4 into an empty cache, groups longest-first by traces/team16_plazy_e3 -> tree8_e0
#   e1   replay traces/team16_plazy_e5 through it, longest-first by tree8_e0 (as osw_loop.py --longest-first) -> tree8_e1
# The no-cache controls are v3's: split_e4_control (file order) and split_e4_lpt (longest-first by team16_plazy_e3).
# Cache: --prefix-depth 8 --prefix-tree (leaf-first eviction, roots last) --prefix-policy gdsf (evict the cheapest to
# lose: step desktop time x (1 + hits), aged) --prefix-admit-cost 10 (save only if (visits of the parent - 1) x the
# desktop time of the path from the root to it >= 10 s) --prefix-lazy-start, shared clones. Each cache epoch: equiv_check.py, tree_check.py; then pmem_report.py
# and timeline_breakdown.py over split_e4_control, split_e4_lpt, tree8_e0, tree8_e1. Snapshots removed at the end.
#   bash run_tree8_v4.sh
set -uo pipefail
cd "$(dirname "$0")"
REPO="$(cd ../.. && pwd)"; C=$PWD/traces/tree8_cache; B=${BUDGET:-40}
PT="sudo -n env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf $REPO/podman-tfork.sh"
uncache() {
    [ -f "$1/index.json" ] && sudo -n venv/bin/python -I -c "import json,sys; [print(e.get('mem') or e.get('clone')) for e in json.load(open(sys.argv[1])).values() if e and (e.get('mem') or e.get('clone'))]" "$1/index.json" \
        | xargs -r $PT rm -f -t 0 >/dev/null 2>&1
    sudo -n rm -rf "$1"
}
run() {   # result dir, recording, extra osw_run.py args...
    d=traces/$1; rec=$2; shift 2
    sudo -n rm -rf $d
    echo "$(date +%T) start $d (replay $rec) $*"
    sudo -n env DOUBAO_API_URL=http://127.0.0.1:1/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system tfork \
        --tasks grpo_batch16_team.json --os4agent $REPO --storage-conf /mnt/data/btrfs/podman/storage.conf --result-dir $d \
        --rollouts 8 --parallel 8 --replay $rec --replay-latency 1 --overlay-rootfs 0 --clone-copies-limit 16 "$@" \
        > $d.log 2>&1 || echo "osw_run exited $?"
    sudo -n chown -R "$(id -u):$(id -g)" $d $d.log
}
CACHE="--prefix-cache $C --prefix-depth 8 --prefix-mem --prefix-lazy --prefix-lazy-start --prefix-tree --prefix-policy gdsf
       --prefix-admit-cost 10 --prefix-mem-budget-gib $B"
epoch() {   # epoch, recording, order-by dir
    run tree8_e$1 $2 $CACHE --order-by $3 --epoch $1
    sudo -n chown -R "$(id -u):$(id -g)" $C
    { echo "== traces/tree8_e$1 (replay $2, longest-first by $3, budget $B GiB) $(date +%T)"
      venv/bin/python -I equiv_check.py traces/tree8_e$1 $2 | grep -vE "^  (chrome|gimp|libreoffice)"
      venv/bin/python -I tree_check.py traces/tree8_e$1 $C; } > traces/tree8_e$1.summary.txt 2>&1
    cat traces/tree8_e$1.summary.txt
}
[ "$($PT ps -aq | wc -l)" = 0 ] || { echo "containers are running: not starting"; exit 1; }
uncache $C
epoch 0 traces/team16_plazy_e4 traces/team16_plazy_e3
epoch 1 traces/team16_plazy_e5 traces/tree8_e0
rm -rf traces/tree8_cache_final && mkdir -p traces/tree8_cache_final && cp $C/index.json traces/tree8_cache_final/
uncache $C
echo "=== performance (split_e4_control: e4 recording, no cache, file order)"
R="traces/split_e4_control traces/split_e4_lpt traces/tree8_e0 traces/tree8_e1"
venv/bin/python -I pmem_report.py $R --csv traces/tree8_v4_report.csv
venv/bin/python -I timeline_breakdown.py $(for r in $R; do echo "$r=$(basename $r)"; done) --csv traces/tree8_v4_timeline.csv | grep -vE "^  slot"
echo "$(date +%T) all done; containers left: $($PT ps -aq | wc -l)"
