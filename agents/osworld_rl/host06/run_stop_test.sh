#!/bin/bash
# --stop-repeats 3 check: replay fix16 Calc pivot rollout 0 (same drag repeated), expect a stop around step 6.
cd /mnt/ssd2/vikranth/osworld
rm -rf traces/stop_test
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py --system tfork --spec off --model replay --tasks pivot1.json --rollouts 1 --max-steps 15 \
  --replay traces/fix16_shot --stop-repeats 3 --replay-latency 0 --result-dir traces/stop_test --parallel 0 --release-copies 1 --obs-timeout 600 > traces/stop_test.log 2>&1
echo "rc=$?"
