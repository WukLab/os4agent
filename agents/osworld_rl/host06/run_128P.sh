#!/bin/bash
# 16x8 cap-20: speculation replay P of rec128_shot, after replay A. Pre-fork + race + early drop + --spec-slow +
# --spec-priority, <= 24 live copies, <= 2 clones in progress, no speculation until all rollouts have fanned out.
cd /mnt/ssd2/vikranth/osworld
while sudo tmux has-session -t "=r128A" 2>/dev/null; do sleep 15; done
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"
rm -rf traces/r128_P
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py --system tfork --model replay --tasks grpo16.json --rollouts 8 --max-steps 20 \
  --replay traces/rec128_shot --replay-latency 1.0 $RUN --spec tage --spec-exec 1 --spec-prefork 1 --spec-from 3 --spec-slow 1 \
  --spec-priority 1 --spec-max-forks 24 --spec-fork-inflight 2 \
  --spec-warm traces/diff15_shot,traces/stuck_shot,traces/lo3_shot,traces/fix16_shot,traces/cap30_shot,traces/rec30_shot \
  --result-dir traces/r128_P > traces/r128_P.log 2>&1
echo "P rc=$? $(date +%T)"
