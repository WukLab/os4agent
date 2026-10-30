#!/bin/bash
# quick validation: no cache / save (unlimited depth, non-blocking) / read-only (overlay on) on the 2-task replay at 0.25x model latency
cd /mnt/ssd2/vikranth/osworld
C="--system tfork --release-copies 1 --obs-timeout 600 --mem-limit-gib 220 --parallel 0 --tasks pfx_test_tasks.json --rollouts 8 \
  --replay traces/grpo_tfork16_e0 --replay-latency 0.25 --setup-concurrency 2 --fork-concurrency 4"
venv/bin/python osw_run.py $C --overlay-rootfs 1 --result-dir traces/qv_A > traces/qv_A.log 2>&1; echo "A rc=$?"
venv/bin/python osw_run.py $C --overlay-rootfs 0 --prefix-cache pfx_qv --prefix-clear 1 --result-dir traces/qv_S > traces/qv_S.log 2>&1; echo "S rc=$?"
venv/bin/python osw_run.py $C --overlay-rootfs 1 --prefix-cache pfx_qv --prefix-save 0 --result-dir traces/qv_R > traces/qv_R.log 2>&1; echo "R rc=$?"
echo done > traces/qv.done
