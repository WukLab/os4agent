#!/bin/bash
# Resume the Thinking GRPO runs at epoch 2 (epochs 2-4): reg first, then spec. Each run continues from its own epoch-2
# adapter; every policy is served as fp16 merged weights at 0.9 of the GPU, without LoRA (vLLM restarted fresh around
# each training). Spec warms TAGE from its own earlier epochs only.
cd /mnt/ssd2/vikranth/osworld
rm -f run_think_rest.done
export A11Y_REASON=1 A11Y_THINK_BUDGET=1024
POD="ssh -i /home/vikranth/.ssh/runpod_wa -o ServerAliveInterval=30 -p 19413 root@64.247.201.57"
COMMON="--system tfork --start-epoch 2 --epochs 5 --keep-going --pod-key /home/vikranth/.ssh/runpod_wa --pod root@64.247.201.57 --pod-port 19413 \
  --base Qwen/Qwen3-VL-8B-Thinking --base-served qwen3vl8b-think --train-args=--max-len=8192 --vllm-util 0.9 --serve-merged"
RUN="--groups 16 --parallel 0 --release-copies 1 --obs-timeout 600 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220"
# fp16 merged copies of both epoch-2 adapters (my bf16/fp16 test merges removed first: pod disk)
$POD 'bash /root/vllm_ctl.sh stop; rm -rf /root/merged/test_bfloat16 /root/merged/test_float16 /root/merged/grpo_think_reg/e2; cd /root/osworld_rl &&
  for x in reg spec; do HF_HOME=/root/hf /root/venv/bin/python merge_lora.py --base Qwen/Qwen3-VL-8B-Thinking \
    --adapter /root/adapters/grpo_think_$x/e2 --out /root/merged/grpo_think_$x/e2 --dtype float16 2>&1 | grep merged; done; df -h /root | tail -1'
for x in reg spec; do
  $POD "bash /root/vllm_ctl.sh stop; bash /root/vllm_ctl.sh start 0.9 0 /root/merged/grpo_think_$x/e2 grpo_think_$x-pol2"
  extra=""; [ $x = spec ] && extra="--spec-exec 2 --spec-from 3 --spec-below 64 --spec-max-forks 10"
  venv/bin/python osw_loop.py --exp grpo_think_$x $COMMON --init-adapter /root/adapters/grpo_think_$x/e2 \
    $([ $x = spec ] && echo --spec-warm-own) --run-args "$RUN $extra"; echo "$x rc=$?"
done
echo done > run_think_rest.done
