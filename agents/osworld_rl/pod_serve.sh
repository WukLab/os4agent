#!/bin/bash
# On the GPU pod: vLLM 0.11 serving Qwen3-VL-8B-Instruct as qwen3vl8b on :8000 (text-only a11y agent), as in the recorded runs.
# LoRA is on so osw_loop.py can hot-load each epoch's adapter (rank 16 = train_grpo.py --lora-r).
# For the GRPO loop run with GPU_UTIL=0.4: the trainer shares this GPU and needs the rest of its memory.
set -e; export HF_HOME=/root/hf VLLM_ALLOW_RUNTIME_LORA_UPDATING=True
command -v uv >/dev/null || pip install -q --break-system-packages uv
[ -x /root/venv/bin/vllm ] || { uv venv -p 3.12 /root/venv && uv pip install -p /root/venv/bin/python "vllm==0.11.0" "transformers==4.57.1" peft accelerate --torch-backend=cu128; }
export PATH=/root/venv/bin:$PATH
nohup vllm serve Qwen/Qwen3-VL-8B-Instruct --served-model-name qwen3vl8b --port 8000 --max-model-len 32768 \
  --limit-mm-per-prompt '{"image":0,"video":0}' --enable-prefix-caching --gpu-memory-utilization ${GPU_UTIL:-0.9} \
  --enable-lora --max-lora-rank 16 --max-loras 2 > /root/vllm.log 2>&1 &
until curl -sf localhost:8000/v1/models >/dev/null; do sleep 5; done; echo SERVING > /root/serve.status
