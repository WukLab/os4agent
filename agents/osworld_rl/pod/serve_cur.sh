#!/bin/bash
# On the GPU pod: vLLM 0.11 serving Qwen3-VL-8B-Instruct as qwen3vl8b on :8000 (text-only a11y agent), as in the recorded runs.
# LORA=1 (default) lets osw_loop.py hot-load each epoch's adapter (rank 16 = train_grpo.py --lora-r); LORA=0 for
# inference only.
# For the GRPO loop run with GPU_UTIL=0.4: the trainer shares this GPU and needs the rest of its memory.
set -e; export HF_HOME=/root/hf VLLM_ALLOW_RUNTIME_LORA_UPDATING=True
LORA_ARGS=""; [ "${LORA:-1}" = 1 ] && LORA_ARGS="--enable-lora --max-lora-rank 16 --max-loras 2"
# EAGER=1: no CUDA graphs / torch.compile. On an H100, vLLM 0.11 died with "CUDA error: an illegal memory access" in
# decode within minutes of real agent traffic, with and without LoRA (the same build is stable on A100).
[ "${EAGER:-0}" = 1 ] && LORA_ARGS="$LORA_ARGS --enforce-eager"
command -v uv >/dev/null || pip install -q --break-system-packages uv
[ -x /root/venv/bin/vllm ] || { uv venv -p 3.12 /root/venv && uv pip install -p /root/venv/bin/python "vllm==0.11.0" "transformers==4.57.1" peft accelerate --torch-backend=cu128; }
export PATH=/root/venv/bin:$PATH
nohup vllm serve Qwen/Qwen3-VL-8B-Instruct --served-model-name qwen3vl8b --dtype float16 --port 8000 --max-model-len 32768 \
  --limit-mm-per-prompt '{"image":0,"video":0}' --enable-prefix-caching --gpu-memory-utilization ${GPU_UTIL:-0.9} \
  $LORA_ARGS > /root/vllm.log 2>&1 &
until curl -sf localhost:8000/v1/models >/dev/null; do sleep 5; done; echo SERVING > /root/serve.status
