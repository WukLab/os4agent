#!/bin/bash
# AgentENV baseline: replay of epoch 0 (rec128_shot), same settings as r128_A / r128_criu, no speculation.
# Waits for run_e2.sh (its replays measure timing; 128 VMs alongside would skew them), then a 1-group smoke test,
# then the full 16x8 only if the smoke test exits cleanly.
cd /mnt/ssd2/vikranth/osworld
until grep -q "^rc=done" traces/run_e2.out 2>/dev/null; do sleep 30; done
echo "e2 done $(date +%T)"
RUN="--parallel 0 --release-copies 1 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --obs-timeout 120"
COMMON="--system aenv --model replay --rollouts 8 --max-steps 20 --replay traces/rec128_shot --replay-latency 1.0 $RUN --spec off"
rm -rf traces/aenv_smoke traces/r128_aenv
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py $COMMON --tasks aenv_smoke.json --result-dir traces/aenv_smoke > traces/aenv_smoke.log 2>&1
rc=$?; echo "smoke rc=$rc $(date +%T)"
[ $rc -eq 0 ] || { echo "rc=smoke_failed"; exit 1; }
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py $COMMON --tasks grpo16.json --result-dir traces/r128_aenv > traces/r128_aenv.log 2>&1
echo "aenv rc=$? $(date +%T)"
echo "rc=done"
