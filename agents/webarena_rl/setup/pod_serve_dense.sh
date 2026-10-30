#!/bin/bash
# On the GPU pod: vLLM 0.11 serving Qwen3-VL-8B-Instruct as qwen3vl8b on :8000, dense (no LoRA): the teammate's
# agents/osworld_rl/pod_serve.sh without --enable-lora / --max-lora-rank / --max-loras (one epoch of inference; vLLM
# LoRA had errors on H100). Writes /root/serve.status = SERVING once the server answers; log /root/vllm.log.
set -e; export HF_HOME=/root/hf
command -v uv >/dev/null || pip install -q --break-system-packages uv
[ -x /root/venv/bin/vllm ] || { uv venv -p 3.12 /root/venv && uv pip install -p /root/venv/bin/python "vllm==0.11.0" "transformers==4.57.1" accelerate --torch-backend=cu128; }
export PATH=/root/venv/bin:$PATH
nohup vllm serve Qwen/Qwen3-VL-8B-Instruct --served-model-name qwen3vl8b --port 8000 --max-model-len 32768 \
  --limit-mm-per-prompt '{"image":0,"video":0}' --enable-prefix-caching --gpu-memory-utilization ${GPU_UTIL:-0.9} \
  > /root/vllm.log 2>&1 &
until curl -sf localhost:8000/v1/models >/dev/null; do sleep 5; done; echo SERVING > /root/serve.status
