#!/bin/bash
# Epoch 5 again with a higher thinking budget (A11Y_THINK_BUDGET 1536 instead of 1024), everything else as rec128e5_shot:
# policy pol6s (served on the training pod, tunnel 06:8100), live 16x8 cap 20, tfork, screen cache warmed on epochs 1-4.
cd /mnt/ssd2/vikranth/osworld
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"
rm -rf traces/rec128e5b_shot
env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x A11Y_REASON=1 A11Y_THINK_BUDGET=1536 A11Y_SCREENSHOT=1 \
  venv/bin/python osw_run.py --system tfork --spec off --model grpo_think_reg-pol6s --tasks grpo16.json --rollouts 8 --max-steps 20 \
  --screen-cache 1 --screen-warm traces/rec128_shot,traces/rec128e2_shot,traces/rec128e3_shot,traces/rec128e4_shot \
  --result-dir traces/rec128e5b_shot $RUN > traces/rec128e5b_shot.log 2>&1
echo "record rc=$? $(date +%T)"
echo "rc=done"
