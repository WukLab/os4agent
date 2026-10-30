#!/bin/bash
# 16x8 cap-20: baseline replay A of rec128_shot (no speculation).
cd /mnt/ssd2/vikranth/osworld
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"
rm -rf traces/r128_A
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py --system tfork --model replay --tasks grpo16.json --rollouts 8 --max-steps 20 \
  --replay traces/rec128_shot --replay-latency 1.0 $RUN --spec off --result-dir traces/r128_A > traces/r128_A.log 2>&1
echo "A rc=$? $(date +%T)"
