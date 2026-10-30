#!/bin/bash
# quick 8x8 speculation stress test with the keep_failed_clone fix: 6 steps per rollout, speculation from step 3 for
# every rollout (no tail limit). Checks failed forks stay isolated (no 'resolve parent snap-ro' cascades).
cd /mnt/ssd2/vikranth/osworld
venv/bin/python osw_run.py --system tfork --release-copies 1 --obs-timeout 600 --mem-limit-gib 220 --parallel 0 \
  --tasks spec_tail8.json --rollouts 8 --max-steps 6 --replay traces/grpo_tfork16_e2 --replay-latency 4.5 --setup-concurrency 2 \
  --spec-exec 2 --spec-from 3 --spec-below 0 --spec-warm traces/grpo_tfork16_e0,traces/grpo_tfork16_e1 \
  --result-dir traces/spec_stress8 > traces/spec_stress8.log 2>&1; echo "stress rc=$?"
