#!/bin/bash
# Policy 2 (in-memory prefix tree, port of WukLab/os4agent 2e8a724) on our epochs, their settings (depth 8, gdsf,
# admit cost 10 s, 40 GiB budget, lazy start, clone limit 16, overlay rootfs off). Cold cache: replay epoch 1
# (rec128_shot) to fill it, then replay epoch 2 (rec128e2_shot) through it = the measured run. Starts after the
# screen-cache rerun (run_e2_SC2.sh). Compare r128e2_TREE with the live recording (20.78 min) / P2 / SC2.
cd /mnt/ssd2/vikranth/osworld
until grep -q "^rc=done" traces/run_e2_SC2.out 2>/dev/null; do sleep 30; done
echo "start $(date +%T)"
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"
TREE="--overlay-rootfs 0 --tree-cache traces/tree_cache_p2 --tree-depth 8 --tree-budget-gib 40 --tree-policy gdsf --tree-admit-cost 10 --tree-lazy-start 1 --clone-copies-limit 16"
rm -rf traces/tree_cache_p2 traces/r128e1_TREE traces/r128e2_TREE
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py --system tfork --model replay --tasks grpo16.json --rollouts 8 --max-steps 20 \
  --replay traces/rec128_shot --replay-latency 1.0 $RUN --spec off $TREE --epoch 1 --result-dir traces/r128e1_TREE > traces/r128e1_TREE.log 2>&1
echo "fill (epoch 1) rc=$? $(date +%T)"
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py --system tfork --model replay --tasks grpo16.json --rollouts 8 --max-steps 20 \
  --replay traces/rec128e2_shot --replay-latency 1.0 $RUN --spec off $TREE --epoch 2 --result-dir traces/r128e2_TREE > traces/r128e2_TREE.log 2>&1
echo "measure (epoch 2) rc=$? $(date +%T)"
echo "rc=done"
