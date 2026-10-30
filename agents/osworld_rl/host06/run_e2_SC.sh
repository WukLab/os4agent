#!/bin/bash
# Screen cache (--screen-cache 1) replay of epoch 2 (rec128e2_shot): cached next screen served at once, the rollout desktop
# runs the action in the background, real screen checked before the next step. Warm: every earlier *_shot trace except
# epoch 2 itself. No speculation. Compare with the live recording (20.78 min, 45/128) and r128e2_P2 (19.21 min).
cd /mnt/ssd2/vikranth/osworld
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"
rm -rf traces/r128e2_SC
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py --system tfork --model replay --tasks grpo16.json --rollouts 8 --max-steps 20 \
  --replay traces/rec128e2_shot --replay-latency 1.0 $RUN --spec off --screen-cache 1 --screen-warm traces/cap30_shot,traces/diff15_shot,traces/fix16_shot,traces/incA_shot,traces/lo3_shot,traces/rec128_shot,traces/rec30_shot,traces/shot6_shot,traces/shot6v2_shot,traces/shot6v3_shot,traces/shot6v4_shot,traces/stop15_shot,traces/stuck_shot,traces/vlc1_shot \
  --result-dir traces/r128e2_SC > traces/r128e2_SC.log 2>&1
echo "SC rc=$? $(date +%T)"
echo "rc=done"
