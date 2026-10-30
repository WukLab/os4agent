#!/bin/bash
# B2 = B with the fixes: retired desktops stopped (not removed) until the rollout ends, spec forks one attempt and no
# --persistent. Waits for the spec_tail session (A, B) to end first so runs don't overlap.
cd /mnt/ssd2/vikranth/osworld
C="--system tfork --release-copies 1 --obs-timeout 600 --mem-limit-gib 220 --parallel 0 --tasks spec_tail3.json --rollouts 8 \
  --replay traces/grpo_tfork16_e2 --replay-latency 4.5 --setup-concurrency 2"
venv/bin/python osw_run.py $C --spec-exec 2 --spec-from 3 --spec-below 64 --spec-warm traces/grpo_tfork16_e0,traces/grpo_tfork16_e1 \
  --result-dir traces/spec_tail_B2 > traces/spec_tail_B2.log 2>&1; echo "B2 rc=$?"
