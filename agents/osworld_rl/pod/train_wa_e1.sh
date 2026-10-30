#!/bin/bash
# On the pod: one GRPO update (fresh LoRA) of Qwen3-VL-8B-Instruct on the WebArena-Lite 16x8 epoch (lite32_h100_r3,
# tasks 29-77), text-only agent; merge (fp16) and serve as wa-pol1 (no images).
cd /root/osworld_rl
B=Qwen/Qwen3-VL-8B-Instruct; D=/root/data/wa_e1; OUT=/root/adapters/wa/e1; M=/root/merged/wa/e1
echo "== download $(date +%T)"
HF_HOME=/root/hf /root/venv/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('$B')" 2>&1 | tail -1
bash /root/vllm_ctl.sh stop
echo "== train $(date +%T)"
HF_HOME=/root/hf /root/venv/bin/python train_grpo.py --base $B --data $D --out $OUT --max-len=8192 --lr 5e-5 --minibatches 4 \
  || { echo "TRAIN FAILED"; exit 1; }
echo "== merge $(date +%T)"
HF_HOME=/root/hf /root/venv/bin/python merge_lora.py --base $B --adapter $OUT --out $M --dtype float16 2>&1 | tail -1
echo "== serve $(date +%T)"
IMAGES=0 bash /root/vllm_ctl.sh start 0.9 0 $M wa-pol1
echo "== done $(date +%T)"
