#!/bin/bash
# Cap-30 spec A/B: replay rec30 (new grpo16 x 2, cap 30, no repeat stop); A = no spec, B = in-place spec, --spec-slow, <= 64 backups.
cd /mnt/ssd2/vikranth/osworld
while sudo tmux has-session -t "=rec30" 2>/dev/null; do sleep 10; done
COMMON="--system tfork --model replay --tasks grpo16.json --rollouts 2 --max-steps 30 --obs-timeout 120 --replay traces/rec30_shot --replay-latency 1.0 --parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220"
rm -rf traces/ab30_A traces/ab30_B
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py $COMMON --spec off --result-dir traces/ab30_A > traces/ab30_A.log 2>&1 &
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py $COMMON --spec tage --spec-exec 1 --spec-inplace 1 --spec-from 3 --spec-slow 1 --spec-max-forks 64 \
  --spec-warm traces/diff15_shot,traces/stuck_shot,traces/lo3_shot,traces/fix16_shot,traces/cap30_shot --result-dir traces/ab30_B > traces/ab30_B.log 2>&1 &
wait
echo "rc=done $(date +%T)"
