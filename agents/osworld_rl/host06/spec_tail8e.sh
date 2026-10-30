#!/bin/bash
# B8e = B8d + --spec-tail-tasks 3 (speculate only for the 3 tasks whose rollouts took longest in epochs 0-1: the long tail).
cd /mnt/ssd2/vikranth/osworld
while tmux has-session -t "=b8d" 2>/dev/null; do sleep 10; done  # start after B8d
C="--system tfork --release-copies 1 --obs-timeout 600 --mem-limit-gib 220 --parallel 0 --tasks spec_tail8.json --rollouts 8 \
  --replay traces/grpo_tfork16_e2 --replay-latency 4.5 --setup-concurrency 2"
venv/bin/python osw_run.py $C --spec-exec 2 --spec-from 3 --spec-below 64 --spec-max-forks 10 --spec-tail-tasks 3 --spec-warm traces/grpo_tfork16_e0,traces/grpo_tfork16_e1 \
  --result-dir traces/spec_tail_B8e > traces/spec_tail_B8e.log 2>&1; echo "B8e rc=$?"
