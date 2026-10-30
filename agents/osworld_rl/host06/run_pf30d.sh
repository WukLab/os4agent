#!/bin/bash
# Pre-fork v4: race + early drop of wrong guesses, <= 24 live copies, P arm only; baseline = ab30_A.
cd /mnt/ssd2/vikranth/osworld
COMMON="--system tfork --model replay --tasks grpo16.json --rollouts 2 --max-steps 30 --obs-timeout 120 --replay traces/rec30_shot --replay-latency 1.0 --parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220"
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py $COMMON --spec tage --spec-exec 1 --spec-prefork 1 --spec-from 3 --spec-slow 1 --spec-max-forks 24 \
  --spec-warm traces/diff15_shot,traces/stuck_shot,traces/lo3_shot,traces/fix16_shot,traces/cap30_shot --result-dir traces/pf30d_P > traces/pf30d_P.log 2>&1 &
wait
echo "rc=done $(date +%T)"
