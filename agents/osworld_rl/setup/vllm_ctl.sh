#!/bin/bash
# On the pod: vllm_ctl.sh stop | start [GPU_UTIL] [LORA] [MODEL] [SERVED]
#   stop   stop vLLM (frees the GPU for training)
#   start  serve MODEL (default the base Qwen/Qwen3-VL-8B-Thinking) as SERVED (default qwen3vl8b-think) and wait until
#          it answers, always in float16 (merged policies are fp16: bf16 rounds small GRPO updates away). Defaults
#          GPU_UTIL=0.9 LORA=1; eager unless EAGER=0 (CUDA graphs + torch.compile). MODEL can be a merged policy dir (merge_lora.py --dtype float16), LORA=0.
case $1 in
stop)
  pgrep -f "bin/vllm serve" | xargs -r kill
  for i in $(seq 60); do pgrep -f "bin/vllm serve" >/dev/null || break; sleep 2; done
  pgrep -f "bin/vllm serve" | xargs -r kill -9; sleep 3
  echo "stopped, GPU memory used: $(nvidia-smi --query-gpu=memory.used --format=csv,noheader)" ;;
start)
  MODEL=${4:-Qwen/Qwen3-VL-8B-Thinking}; SERVED=${5:-qwen3vl8b-think}
  sed "s#Qwen/Qwen3-VL-8B-Thinking --served-model-name qwen3vl8b-think#$MODEL --served-model-name $SERVED --dtype float16#" /root/serve_think.sh > /root/serve_cur.sh
  [ "${IMAGES:-0}" = 1 ] && sed -i 's/"image":0/"image":1/' /root/serve_cur.sh  # IMAGES=1: one image per prompt (A11Y_SCREENSHOT=1)
  rm -f /root/serve.status
  cd /root && GPU_UTIL=${2:-0.9} LORA=${3:-1} EAGER=${EAGER:-1} nohup bash serve_cur.sh > serve_cur.out 2>&1 < /dev/null &
  for i in $(seq 120); do [ -f /root/serve.status ] && break; sleep 5; done
  [ -f /root/serve.status ] && echo "serving $SERVED from $MODEL (GPU_UTIL=${2:-0.9} LORA=${3:-1} IMAGES=${IMAGES:-0}): $(grep -o 'GPU KV cache size: [0-9,]* tokens' /root/vllm.log | tail -1)" \
    || { echo "vLLM did not come up"; tail -5 /root/vllm.log; exit 1; } ;;
*) echo "usage: $0 stop | start [GPU_UTIL] [LORA] [MODEL] [SERVED]"; exit 1 ;;
esac
