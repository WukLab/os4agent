#!/bin/bash
# saving replay (S) with --fork-concurrency 8 and 16; compare with qv_S (4)
cd /mnt/ssd2/vikranth/osworld
C="--system tfork --release-copies 1 --obs-timeout 600 --mem-limit-gib 220 --parallel 0 --tasks pfx_test_tasks.json --rollouts 8 \
  --replay traces/grpo_tfork16_e0 --replay-latency 0.25 --setup-concurrency 2 --overlay-rootfs 0"
for fc in 8 16; do
  venv/bin/python osw_run.py $C --fork-concurrency $fc --prefix-cache pfx_fc$fc --prefix-clear 1 --result-dir traces/fc_S$fc > traces/fc_S$fc.log 2>&1; echo "fc $fc rc=$?"
done
echo done > traces/fc.done
