#!/bin/bash
# 16x8 cap-20 CRIU baseline: replay of rec128_shot with our CRIU in CKPT mode (serial full dump+restore per copy,
# --full-memcopy: no CoW with the source), no speculation. Same measurements (mem.jsonl, events.jsonl) as r128_A (tfork).
cd /mnt/ssd2/vikranth/osworld
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"
rm -rf traces/r128_criu
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py --system criu --full-memcopy 1 --model replay --tasks grpo16.json --rollouts 8 --max-steps 20 \
  --replay traces/rec128_shot --replay-latency 1.0 $RUN --spec off --result-dir traces/r128_criu > traces/r128_criu.log 2>&1
echo "criu rc=$? $(date +%T)"
