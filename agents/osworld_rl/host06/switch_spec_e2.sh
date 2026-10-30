#!/bin/bash
# After reg e2's rollouts: stop the resume loop (no training needed), serve spec's epoch-2 policy fresh, run spec e2.
cd /mnt/ssd2/vikranth/osworld
POD="ssh -i /home/vikranth/.ssh/runpod_wa -o ServerAliveInterval=30 -p 19413 root@64.247.201.57"
until grep -q "^epoch 2 grpo_think_reg_e2" traces/run_think_rest.log; do sleep 15; done
echo "$(date +%T) reg e2 rollouts done: $(grep "^epoch 2 grpo_think_reg_e2" traces/run_think_rest.log)"
tmux kill-session -t "=thinkrest"; sleep 3
$POD 'bash /root/stop_train.sh; bash /root/vllm_ctl.sh stop; bash /root/vllm_ctl.sh start 0.9 0 /root/merged/grpo_think_spec/e2 grpo_think_spec-pol2'
RUN="--groups 16 --parallel 0 --release-copies 1 --obs-timeout 600 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220"
rm -rf traces/grpo_think_spec_e2
env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x A11Y_REASON=1 A11Y_THINK_BUDGET=1024 \
  venv/bin/python osw_run.py --system tfork --spec off --model grpo_think_spec-pol2 --tasks grpo_batch32v2.json --rollouts 8 --max-steps 15 \
  --result-dir traces/grpo_think_spec_e2 $RUN --spec-exec 2 --spec-from 3 --spec-below 64 --spec-max-forks 10 \
  --spec-warm traces/grpo_think_spec_e0,traces/grpo_think_spec_e1 > traces/grpo_think_spec_e2.log 2>&1
echo "$(date +%T) spec e2 rc=$?"
