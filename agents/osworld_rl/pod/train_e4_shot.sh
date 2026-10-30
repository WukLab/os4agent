#!/bin/bash
# On the pod: one GRPO update of grpo_think_reg (from e3_shot = pol3s) on the epoch-2 16x8 screenshot recording rec128e2_shot, then serve the
# result as fp16 merged weights with images enabled. Smoke test first (6 samples): a broken image path stops here.
cd /root/osworld_rl
B=Qwen/Qwen3-VL-8B-Thinking; D=/root/data/shot_reg_e3; IN=/root/adapters/grpo_think_reg/e3_shot
OUT=/root/adapters/grpo_think_reg/e4_shot; M=/root/merged/grpo_think_reg/e4_shot
bash /root/vllm_ctl.sh stop
echo "== smoke $(date +%T)"
HF_HOME=/root/hf /root/venv/bin/python train_grpo.py --base $B --data $D --out /tmp/smoke_e4 --init-adapter $IN --max-len=8192 --max-samples 6 \
  || { echo "SMOKE FAILED"; IMAGES=1 bash /root/vllm_ctl.sh start 0.9 0 /root/merged/grpo_think_reg/e3_shot grpo_think_reg-pol3s; exit 1; }
echo "== train $(date +%T)"
HF_HOME=/root/hf /root/venv/bin/python train_grpo.py --base $B --data $D --out $OUT --init-adapter $IN --max-len=8192 --lr 5e-5 --minibatches 4 \
  || { echo "TRAIN FAILED"; IMAGES=1 bash /root/vllm_ctl.sh start 0.9 0 /root/merged/grpo_think_reg/e3_shot grpo_think_reg-pol3s; exit 1; }
echo "== merge $(date +%T)"
HF_HOME=/root/hf /root/venv/bin/python merge_lora.py --base $B --adapter $OUT --out $M --dtype float16 2>&1 | tail -2
echo "== serve $(date +%T)"
IMAGES=1 bash /root/vllm_ctl.sh start 0.9 0 $M grpo_think_reg-pol4s
echo "== done $(date +%T)"
