#!/usr/bin/env bash
# Run ON the RunPod pod (A100, image runpod/pytorch). Serves the model and reverse-tunnels it to 02.
set -e; source "$(dirname "$0")/.env"
command -v uv >/dev/null || pip install -q --break-system-packages uv
[ -d /root/venv ] || { uv venv -p 3.12 /root/venv && uv pip install -p /root/venv/bin/python "vllm${VLLM_VER}" "transformers==4.57.1" peft accelerate --torch-backend=cu128; }   # transformers>=5 breaks vllm 0.11 on VL configs; peft/accelerate = trainer
export PATH=/root/venv/bin:$PATH; mkdir -p ~/.ssh
[ -f ~/.ssh/wuk ] || { echo "put the private key authorized on 02 at ~/.ssh/wuk (chmod 600)"; exit 1; }
# LORA=1 GPU_UTIL=0.4: leave GPU memory for the trainer (GPU_UTIL defaults to 0.9, so set it) and allow hot-loading adapters (see grpo_loop.py)
# MM_LIMIT='{"image":0,"video":0}' for the text-only a11y agent: vLLM 0.11 + LoRA + Qwen3-VL asserts in the vision/video warm-up
MM_LIMIT=${MM_LIMIT:-'{"image":5}'}
EXTRA=""; [ "${LORA:-0}" = 1 ] && { export VLLM_ALLOW_RUNTIME_LORA_UPDATING=True; EXTRA="--enable-lora --max-lora-rank ${LORA_RANK:-16} --max-loras 2"; }
nohup vllm serve $MODEL --served-model-name ${SERVED:-uitars15-7b} --port $LLM_PORT --max-model-len ${MAX_LEN:-32768} --limit-mm-per-prompt "$MM_LIMIT" \
  --enable-prefix-caching --gpu-memory-utilization ${GPU_UTIL:-0.9} $EXTRA > vllm.log 2>&1 &
until curl -sf localhost:$LLM_PORT/v1/models >/dev/null; do sleep 5; done   # (tunnel below)
# 02:$LLM_PORT -> this pod's vLLM. Reverse so 02 (behind campus NAT) never needs to reach RunPod.
exec ssh -N -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -i ~/.ssh/wuk -p $WUK_PORT \
  -R $LLM_PORT:localhost:$LLM_PORT $WUK_USER@$WUK_HOST
