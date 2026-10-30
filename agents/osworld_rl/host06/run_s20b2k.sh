#!/bin/bash
# Longer budget + more steps: reg vs spec with the SAME policy (reg's fp16 merged epoch-2 weights, 0.9 GPU, fresh vLLM
# for each), --max-steps 20, thinking budget 2048. Compare with grpo_think_reg_e2 / grpo_think_specsame_e2 (15 / 1024).
cd /mnt/ssd2/vikranth/osworld
POD="ssh -i /home/vikranth/.ssh/runpod_wa -o ServerAliveInterval=30 -p 19413 root@64.247.201.57"
RUN="--groups 16 --parallel 0 --release-copies 1 --obs-timeout 600 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220"
SPEC="--spec-exec 2 --spec-from 3 --spec-below 64 --spec-max-forks 10 --spec-warm traces/grpo_think_reg_e0,traces/grpo_think_reg_e1"
for x in reg spec; do
  $POD 'bash /root/vllm_ctl.sh stop; bash /root/vllm_ctl.sh start 0.9 0 /root/merged/grpo_think_reg/e2 grpo_think_reg-pol2'
  rm -rf traces/s20b2k_$x
  env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x A11Y_REASON=1 A11Y_THINK_BUDGET=2048 \
    venv/bin/python osw_run.py --system tfork --spec off --model grpo_think_reg-pol2 --tasks grpo_batch32v2.json --rollouts 8 --max-steps 20 \
    --result-dir traces/s20b2k_$x $RUN $([ $x = spec ] && echo "$SPEC") > traces/s20b2k_$x.log 2>&1
  echo "$(date +%T) $x rc=$?"
done
