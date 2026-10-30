#!/bin/bash
# Speculation check with the SAME policy as reg e2: fresh vLLM on reg's fp16 merged epoch-2 weights, reg e2's settings
# + speculation, TAGE warmed from reg e0-e1 (that policy's history so far). Only difference from reg e2: speculation.
cd /mnt/ssd2/vikranth/osworld
POD="ssh -i /home/vikranth/.ssh/runpod_wa -o ServerAliveInterval=30 -p 19413 root@64.247.201.57"
$POD 'bash /root/vllm_ctl.sh stop; bash /root/vllm_ctl.sh start 0.9 0 /root/merged/grpo_think_reg/e2 grpo_think_reg-pol2'
RUN="--groups 16 --parallel 0 --release-copies 1 --obs-timeout 600 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220"
rm -rf traces/grpo_think_specsame_e2
env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x A11Y_REASON=1 A11Y_THINK_BUDGET=1024 \
  venv/bin/python osw_run.py --system tfork --spec off --model grpo_think_reg-pol2 --tasks grpo_batch32v2.json --rollouts 8 --max-steps 15 \
  --result-dir traces/grpo_think_specsame_e2 $RUN --spec-exec 2 --spec-from 3 --spec-below 64 --spec-max-forks 10 \
  --spec-warm traces/grpo_think_reg_e0,traces/grpo_think_reg_e1 > traces/grpo_think_specsame_e2.log 2>&1
echo "$(date +%T) specsame e2 rc=$?"
