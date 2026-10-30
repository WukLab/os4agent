#!/bin/bash
# speculation sanity check on the long tail: replay epoch 2 of grpo_tfork16 on its 3 tail Calc tasks (24 rollouts),
# model time stretched 4.5x (~Thinking at this batch size). A = no spec, B = TAGE top-2 forks from step 3, TAGE and the
# action book warmed with epochs 0-1.
cd /mnt/ssd2/vikranth/osworld
C="--system tfork --release-copies 1 --obs-timeout 600 --mem-limit-gib 220 --parallel 0 --tasks spec_tail3.json --rollouts 8 \
  --replay traces/grpo_tfork16_e2 --replay-latency 4.5 --setup-concurrency 2"
venv/bin/python osw_run.py $C --result-dir traces/spec_tail_A > traces/spec_tail_A.log 2>&1; echo "A rc=$?"
venv/bin/python osw_run.py $C --spec-exec 2 --spec-from 3 --spec-below 64 --spec-warm traces/grpo_tfork16_e0,traces/grpo_tfork16_e1 \
  --result-dir traces/spec_tail_B > traces/spec_tail_B.log 2>&1; echo "B rc=$?"
