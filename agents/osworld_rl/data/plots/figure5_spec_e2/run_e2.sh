#!/bin/bash
# Epoch 2: live 16x8 cap-20 recording with policy grpo_think_reg-pol3s (one GRPO update on epoch 1 = rec128_shot,
# screenshot-aware trainer), then replays A_e2 (no spec) and P2_e2 (P2 settings, TAGE also warmed on epoch 1), one after
# the other. The same-element-drag no-op is in a11y_owl_agent.py for all three.
cd /mnt/ssd2/vikranth/osworld
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"
rm -rf traces/rec128e2_shot traces/r128e2_A traces/r128e2_P2
echo "record start $(date +%T)"
env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x A11Y_REASON=1 A11Y_THINK_BUDGET=1024 A11Y_SCREENSHOT=1 \
  venv/bin/python osw_run.py --system tfork --spec off --model grpo_think_reg-pol3s --tasks grpo16.json --rollouts 8 --max-steps 20 \
  --result-dir traces/rec128e2_shot $RUN > traces/rec128e2_shot.log 2>&1
echo "record rc=$? $(date +%T)"
COMMON="--system tfork --model replay --tasks grpo16.json --rollouts 8 --max-steps 20 --replay traces/rec128e2_shot --replay-latency 1.0 $RUN"
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py $COMMON --spec off --result-dir traces/r128e2_A > traces/r128e2_A.log 2>&1
echo "A rc=$? $(date +%T)"
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py $COMMON --spec tage --spec-exec 1 --spec-prefork 1 --spec-from 3 --spec-slow 1 \
  --spec-priority 1 --spec-max-forks 24 --spec-fork-inflight 2 --spec-fork-inflight-tail 8 \
  --spec-warm traces/rec128_shot,traces/diff15_shot,traces/stuck_shot,traces/lo3_shot,traces/fix16_shot,traces/cap30_shot,traces/rec30_shot \
  --result-dir traces/r128e2_P2 > traces/r128e2_P2.log 2>&1
echo "P2 rc=$? $(date +%T)"
echo "rc=done"
