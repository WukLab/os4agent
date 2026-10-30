#!/bin/bash
# Eviction check without model drift, from a cold cache: replay traces/team16_plazy_e4 into an empty cache (tree8_e0,
# longest-first by team16_plazy_e3), then replay the same recording again through it (tree8_same_e1, longest-first by
# tree8_e0). Settings: depth 8, tree, gdsf, admission by path cost, new saves evict only finished groups' non-root
# snapshots (roots only by memory growth), 40 GiB. Identical actions: every step <= 8 whose prefix the first pass saved
# and eviction kept should hit; same_check.py says what admission and eviction lost. Snapshots removed at the end.
#   bash run_tree8_same2.sh
set -uo pipefail
cd "$(dirname "$0")"
REPO="$(cd ../.. && pwd)"; C=$PWD/traces/tree8_cache; B=${BUDGET:-40}
PT="sudo -n env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf $REPO/podman-tfork.sh"
uncache() {
    [ -f "$1/index.json" ] && sudo -n venv/bin/python -I -c "import json,sys; [print(e.get('mem') or e.get('clone')) for e in json.load(open(sys.argv[1])).values() if e and (e.get('mem') or e.get('clone'))]" "$1/index.json" \
        | xargs -r $PT rm -f -t 0 >/dev/null 2>&1
    sudo -n rm -rf "$1"
}
[ "$($PT ps -aq | wc -l)" = 0 ] || { echo "containers are running: not starting"; exit 1; }
uncache $C
CACHE="--prefix-cache $C --prefix-depth 8 --prefix-mem --prefix-lazy --prefix-lazy-start --prefix-tree --prefix-policy gdsf
       --prefix-admit-cost 10 --prefix-mem-budget-gib $B"
d=traces/tree8_e0; rec=traces/team16_plazy_e4
sudo -n rm -rf $d
echo "$(date +%T) start $d (replay $rec into an empty cache)"
sudo -n env DOUBAO_API_URL=http://127.0.0.1:1/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system tfork \
    --tasks grpo_batch16_team.json --os4agent $REPO --storage-conf /mnt/data/btrfs/podman/storage.conf --result-dir $d \
    --rollouts 8 --parallel 8 --replay $rec --replay-latency 1 --overlay-rootfs 0 --clone-copies-limit 16 \
    $CACHE --order-by traces/team16_plazy_e3 --epoch 0 > $d.log 2>&1 || echo "osw_run exited $?"
sudo -n chown -R "$(id -u):$(id -g)" $d $d.log $C
echo "== $d $(date +%T)"
venv/bin/python -I equiv_check.py $d $rec | grep -vE "^  (chrome|gimp|libreoffice)"
venv/bin/python -I tree_check.py $d $C
d=traces/tree8_same_e1; rec=traces/team16_plazy_e4
sudo -n rm -rf $d
echo "$(date +%T) start $d (replay $rec again, cache from tree8_e0: $(venv/bin/python -I -c "import json,sys; print(sum(1 for e in json.load(open(sys.argv[1])).values() if e and e.get('mem')))" $C/index.json) snapshots, roots $(venv/bin/python -I -c "import json,sys; print(sum(1 for e in json.load(open(sys.argv[1])).values() if e and e.get('mem') and e.get('depth') == 0))" $C/index.json))"
sudo -n env DOUBAO_API_URL=http://127.0.0.1:1/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system tfork \
    --tasks grpo_batch16_team.json --os4agent $REPO --storage-conf /mnt/data/btrfs/podman/storage.conf --result-dir $d \
    --rollouts 8 --parallel 8 --replay $rec --replay-latency 1 --overlay-rootfs 0 --clone-copies-limit 16 \
    $CACHE --order-by traces/tree8_e0 --epoch 1 > $d.log 2>&1 || echo "osw_run exited $?"
sudo -n chown -R "$(id -u):$(id -g)" $d $d.log $C
echo "== $d $(date +%T)"
venv/bin/python -I equiv_check.py $d $rec | grep -vE "^  (chrome|gimp|libreoffice)"
venv/bin/python -I tree_check.py $d $C
venv/bin/python -I same_check.py traces/tree8_e0 $d
echo "=== performance (split_e4_lpt: the same recording, no cache, longest-first)"
R="traces/split_e4_lpt traces/tree8_e0 $d"
venv/bin/python -I pmem_report.py $R --csv traces/tree8_same2_report.csv
venv/bin/python -I timeline_breakdown.py $(for r in $R; do echo "$r=$(basename $r)"; done) --csv traces/tree8_same2_timeline.csv | grep -vE "^  slot"
uncache $C
echo "$(date +%T) all done; containers left: $($PT ps -aq | wc -l)"
