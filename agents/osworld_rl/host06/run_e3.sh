#!/bin/bash
# Epoch 3: live 16x8 cap-20 recording with policy grpo_think_reg-pol4s (one GRPO update on epoch 2 = rec128e2_shot,
# from pol3s), tfork, no speculation. Waits until the pod serves pol4s (tunnel 06:8100 -> pod:8000).
cd /mnt/ssd2/vikranth/osworld
until curl -s -m 5 http://127.0.0.1:8100/v1/models | grep -q "grpo_think_reg-pol4s"; do sleep 20; done
echo "pol4s up $(date +%T)"
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"
rm -rf traces/rec128e3_shot
env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x A11Y_REASON=1 A11Y_THINK_BUDGET=1024 A11Y_SCREENSHOT=1 \
  venv/bin/python osw_run.py --system tfork --spec off --model grpo_think_reg-pol4s --tasks grpo16.json --rollouts 8 --max-steps 20 \
  --result-dir traces/rec128e3_shot $RUN > traces/rec128e3_shot.log 2>&1
echo "record rc=$? $(date +%T)"
echo "rc=done"
