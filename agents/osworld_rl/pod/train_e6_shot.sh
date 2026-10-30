#!/bin/bash
# Stub called by run_e45d.sh: pol6s is trained on the 2-GPU pod (data parallel) and 06 pushes the adapter here.
# /root/e6_fallback (touched by 06 if that failed) = train here as before (train_e6_shot_orig.sh).
until [ -f /root/adapters/grpo_think_reg/e6_shot/train_stats.json ] || [ -f /root/e6_fallback ]; do sleep 10; done
[ -f /root/e6_fallback ] && exec bash /root/train_e6_shot_orig.sh
echo "pol6s trained on the 2-GPU pod, adapter pushed here"
echo "== done $(date +%T)"
