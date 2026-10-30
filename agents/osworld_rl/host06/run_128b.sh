#!/bin/bash
# 16x8 speculation test, cap 20: record live (spec off), then replay P first, then A (baseline): (pre-fork + race + early drop +
# --spec-slow + --spec-priority, <= 24 copies), one after the other. Waits for pf30d (v4) first.
cd /mnt/ssd2/vikranth/osworld
while sudo tmux has-session -t "=pf30d" 2>/dev/null; do sleep 15; done
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"
rm -rf traces/rec128_shot traces/r128_A traces/r128_P
echo "record start $(date +%T)"
env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x A11Y_REASON=1 A11Y_THINK_BUDGET=1024 A11Y_SCREENSHOT=1 \
  venv/bin/python osw_run.py --system tfork --spec off --model grpo_think_reg-pol2 --tasks grpo16.json --rollouts 8 --max-steps 20 \
  --result-dir traces/rec128_shot $RUN > traces/rec128_shot.log 2>&1
echo "record rc=$? $(date +%T)"
COMMON="--system tfork --model replay --tasks grpo16.json --rollouts 8 --max-steps 20 --replay traces/rec128_shot --replay-latency 1.0 $RUN"
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py $COMMON --spec tage --spec-exec 1 --spec-prefork 1 --spec-from 3 --spec-slow 1 \
  --spec-priority 1 --spec-max-forks 24 --spec-warm traces/diff15_shot,traces/stuck_shot,traces/lo3_shot,traces/fix16_shot,traces/cap30_shot,traces/rec30_shot \
  --result-dir traces/r128_P > traces/r128_P.log 2>&1
echo "P rc=$? $(date +%T)"
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py $COMMON --spec off --result-dir traces/r128_A > traces/r128_A.log 2>&1
echo "A rc=$? $(date +%T)"
echo "rc=done"
