#!/bin/bash
# B8d = B8c + --spec-max-forks 10 (at most 10 speculation clones at once; a step with no free slot runs normally).
cd /mnt/ssd2/vikranth/osworld
C="--system tfork --release-copies 1 --obs-timeout 600 --mem-limit-gib 220 --parallel 0 --tasks spec_tail8.json --rollouts 8 \
  --replay traces/grpo_tfork16_e2 --replay-latency 4.5 --setup-concurrency 2"
venv/bin/python osw_run.py $C --spec-exec 2 --spec-from 3 --spec-below 64 --spec-max-forks 10 --spec-warm traces/grpo_tfork16_e0,traces/grpo_tfork16_e1 \
  --result-dir traces/spec_tail_B8d > traces/spec_tail_B8d.log 2>&1; echo "B8d rc=$?"
