#!/bin/bash
# Screenshot + accessibility tree vs tree only: reg's epoch-2 policy (fp16 merged, eager, 0.9, images allowed),
# Stop-at-done prompt (A11Y_STOP_DONE=1) on the diff15 tasks, 1 rollout each; baseline = diff15_shot.
cd /mnt/ssd2/vikranth/osworld
RUN="--parallel 0 --release-copies 1 --obs-timeout 600 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220"
for x in shot; do
  rm -rf traces/stop15_$x
  env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x A11Y_REASON=1 A11Y_STOP_DONE=1 A11Y_THINK_BUDGET=1024 A11Y_SCREENSHOT=$([ $x = shot ] && echo 1 || echo 0) \
    venv/bin/python osw_run.py --system tfork --spec off --model grpo_think_reg-pol2 --tasks diff15.json --rollouts 1 --max-steps 15 \
    --result-dir traces/stop15_$x $RUN > traces/stop15_$x.log 2>&1
  echo "$(date +%T) $x rc=$?"
done
