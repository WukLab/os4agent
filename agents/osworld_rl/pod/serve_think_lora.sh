#!/bin/bash
# stop the running vLLM, serve Qwen3-VL-8B-Thinking as qwen3vl8b-think with LoRA (GRPO), 40% GPU (trainer shares it), eager (H100)
pgrep -f "bin/vllm serve" | xargs -r kill; sleep 15
rm -f /root/serve.status
cd /root && LORA=1 EAGER=1 GPU_UTIL=0.4 nohup bash serve_think.sh > serve_think.out 2>&1 < /dev/null &
