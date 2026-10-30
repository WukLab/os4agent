#!/bin/bash
# Screenshot + accessibility tree vs tree only: reg's epoch-2 policy (fp16 merged, eager, 0.9, images allowed),
# 6 tasks x 3 rollouts (shot6.json), 15 steps, thinking budget 1024, no speculation. Same vLLM server for both.
cd /mnt/ssd2/vikranth/osworld
RUN="--parallel 0 --release-copies 1 --obs-timeout 600 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220"
for x in shot; do
  rm -rf traces/shot6v4_$x
  env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x A11Y_REASON=1 A11Y_THINK_BUDGET=1024 A11Y_SCREENSHOT=$([ $x = shot ] && echo 1 || echo 0) \
    venv/bin/python osw_run.py --system tfork --spec off --model grpo_think_reg-pol2 --tasks shot4_unsolved.json --rollouts 3 --max-steps 15 \
    --result-dir traces/shot6v4_$x $RUN > traces/shot6v4_$x.log 2>&1
  echo "$(date +%T) $x rc=$?"
done
