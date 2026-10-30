#!/bin/bash
# Quick spec sanity check: replay fix16 (16 tasks x 2) A = no spec, B = in-place spec with --spec-envbound, in parallel.
cd /mnt/ssd2/vikranth/osworld
COMMON="--system tfork --model replay --tasks grpo16.json --rollouts 2 --max-steps 15 --stop-repeats 3 --obs-timeout 120 --replay traces/fix16_shot --replay-latency 1.0 --parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220"
rm -rf traces/specab_A traces/specab_B
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py $COMMON --spec off --result-dir traces/specab_A > traces/specab_A.log 2>&1 &
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py $COMMON --spec tage --spec-exec 1 --spec-inplace 1 --spec-from 3 --spec-envbound 1 --spec-max-forks 64 \
  --spec-warm traces/diff15_shot,traces/stuck_shot,traces/lo3_shot,traces/cap30_shot --result-dir traces/specab_B > traces/specab_B.log 2>&1 &
wait
echo "rc=done $(date +%T)"
