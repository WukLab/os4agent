#!/bin/bash
# B8c = B8 with the keep_failed_clone fix (a failed fork no longer deletes its group's shared snapshot). Compare with A8.
cd /mnt/ssd2/vikranth/osworld
C="--system tfork --release-copies 1 --obs-timeout 600 --mem-limit-gib 220 --parallel 0 --tasks spec_tail8.json --rollouts 8 \
  --replay traces/grpo_tfork16_e2 --replay-latency 4.5 --setup-concurrency 2"
venv/bin/python osw_run.py $C --spec-exec 2 --spec-from 3 --spec-below 64 --spec-warm traces/grpo_tfork16_e0,traces/grpo_tfork16_e1 \
  --result-dir traces/spec_tail_B8c > traces/spec_tail_B8c.log 2>&1; echo "B8c rc=$?"
