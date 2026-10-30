#!/bin/bash
# tfork + speculation (P2 settings) replay of the second recorded epoch (rec128e2_shot, policy pol3s); TAGE warmed only on the previous epoch (rec128_shot).
# Same settings as r128_P2; compare against the live recording time.
cd /mnt/ssd2/vikranth/osworld
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"
rm -rf traces/r128e2_P2
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py --system tfork --model replay --tasks grpo16.json --rollouts 8 --max-steps 20 \
  --replay traces/rec128e2_shot --replay-latency 1.0 $RUN --spec tage --spec-exec 1 --spec-prefork 1 --spec-from 3 --spec-slow 1 \
  --spec-priority 1 --spec-max-forks 24 --spec-fork-inflight 2 --spec-fork-inflight-tail 8 \
  --spec-warm traces/rec128_shot \
  --result-dir traces/r128e2_P2 > traces/r128e2_P2.log 2>&1
echo "P2 rc=$? $(date +%T)"
echo "rc=done"
