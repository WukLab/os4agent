#!/bin/bash
# 8x8 version of the tail check: epoch 2's 8 slowest tasks (64 rollouts), model time 4.5x. A8 = no spec,
# B8 = TAGE top-2 forks from step 3 while < 64 rollouts are live, warmed with epochs 0-1.
cd /mnt/ssd2/vikranth/osworld
C="--system tfork --release-copies 1 --obs-timeout 600 --mem-limit-gib 220 --parallel 0 --tasks spec_tail8.json --rollouts 8 \
  --replay traces/grpo_tfork16_e2 --replay-latency 4.5 --setup-concurrency 2"
venv/bin/python osw_run.py $C --result-dir traces/spec_tail_A8 > traces/spec_tail_A8.log 2>&1; echo "A8 rc=$?"
venv/bin/python osw_run.py $C --spec-exec 2 --spec-from 3 --spec-below 64 --spec-warm traces/grpo_tfork16_e0,traces/grpo_tfork16_e1 \
  --result-dir traces/spec_tail_B8 > traces/spec_tail_B8.log 2>&1; echo "B8 rc=$?"
