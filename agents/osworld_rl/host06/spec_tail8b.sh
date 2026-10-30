#!/bin/bash
# B8b = B8 + one fix: while speculating, a group's desktops are stopped (not removed) until the whole group is done.
cd /mnt/ssd2/vikranth/osworld
while sudo tmux has-session -t "=spec8" 2>/dev/null; do sleep 10; done
C="--system tfork --release-copies 1 --obs-timeout 600 --mem-limit-gib 220 --parallel 0 --tasks spec_tail8.json --rollouts 8 \
  --replay traces/grpo_tfork16_e2 --replay-latency 4.5 --setup-concurrency 2"
venv/bin/python osw_run.py $C --spec-exec 2 --spec-from 3 --spec-below 64 --spec-warm traces/grpo_tfork16_e0,traces/grpo_tfork16_e1 \
  --result-dir traces/spec_tail_B8b > traces/spec_tail_B8b.log 2>&1; echo "B8b rc=$?"
