#!/bin/bash
# After the epoch-2 recording (pid 546512) exits: kill the paused run_e2.sh (546509) so its replays never start,
# then the AgentENV replay of epoch 0 (rec128_shot), same settings as r128_A / r128_criu, no speculation.
cd /mnt/ssd2/vikranth/osworld
while ps -o stat= -p 546512 | grep -qv Z; do sleep 15; done
kill -9 546509; echo "record done $(date +%T)"; tail -3 traces/rec128e2_shot.log
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"
rm -rf traces/r128_aenv
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py --system aenv --model replay --tasks grpo16.json --rollouts 8 --max-steps 20 \
  --replay traces/rec128_shot --replay-latency 1.0 $RUN --spec off --result-dir traces/r128_aenv > traces/r128_aenv.log 2>&1
echo "aenv rc=$? $(date +%T)"
echo "rc=done"
