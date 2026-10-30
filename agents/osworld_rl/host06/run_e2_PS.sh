#!/bin/bash
# prefix+spec: screen cache (as r128e2_SC2) + P2 pre-fork speculation (as r128e2_P2) on epoch 2 (rec128e2_shot replay).
# Speculation forks only when no cached step is running in the background, and is dropped when the step is a cache hit.
# Screen cache warm: every earlier *_shot trace except epoch 2; TAGE warm: the previous epoch (rec128_shot), as P2.
cd /mnt/ssd2/vikranth/osworld
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"
rm -rf traces/r128e2_PS
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py --system tfork --model replay --tasks grpo16.json --rollouts 8 --max-steps 20 \
  --replay traces/rec128e2_shot --replay-latency 1.0 $RUN \
  --screen-cache 1 --screen-warm traces/cap30_shot,traces/diff15_shot,traces/fix16_shot,traces/incA_shot,traces/lo3_shot,traces/rec128_shot,traces/rec30_shot,traces/shot6_shot,traces/shot6v2_shot,traces/shot6v3_shot,traces/shot6v4_shot,traces/stop15_shot,traces/stuck_shot,traces/vlc1_shot \
  --spec tage --spec-exec 1 --spec-prefork 1 --spec-from 3 --spec-slow 1 --spec-priority 1 --spec-max-forks 24 \
  --spec-fork-inflight 2 --spec-fork-inflight-tail 8 --spec-warm traces/rec128_shot \
  --result-dir traces/r128e2_PS > traces/r128e2_PS.log 2>&1
echo "PS rc=$? $(date +%T)"
echo "rc=done"
