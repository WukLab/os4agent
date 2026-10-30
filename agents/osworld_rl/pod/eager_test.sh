#!/bin/bash
# decode throughput with and without --enforce-eager, 128 and 16 concurrent, merged reg e2 policy (fp16, no LoRA, 0.9)
M=/root/merged/grpo_think_reg/e2
for eager in 1 0; do
  bash /root/vllm_ctl.sh stop >/dev/null
  EAGER=$eager bash /root/vllm_ctl.sh start 0.9 0 $M grpo_think_reg-pol2 || { echo "EAGER=$eager: vLLM did not start"; tail -20 /root/vllm.log; continue; }
  echo "== EAGER=$eager ($(pgrep -af "vllm serve" | grep -c enforce-eager) eager processes)"
  for n in 128 16; do cd /root && /root/venv/bin/python decode_tps.py grpo_think_reg-pol2 $n; done
done
