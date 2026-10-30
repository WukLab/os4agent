#!/bin/bash
# Slower drag check: replay diff15 Calc pivot 1954cced steps 1-5 (Invoice No. drag into the layout).
cd /mnt/ssd2/vikranth/osworld
rm -rf traces/drag_pivot
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py --system tfork --spec off --model replay --tasks pivot1.json --rollouts 1 --max-steps 5 \
  --replay traces/diff15_shot --replay-latency 0 --result-dir traces/drag_pivot --parallel 0 --release-copies 1 --obs-timeout 600 > traces/drag_pivot.log 2>&1
echo "rc=$?"
