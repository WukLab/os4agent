#!/bin/bash
# after tmpl_test.sh: 2-task correctness check of the batched template restore
cd /mnt/ssd2/vikranth/osworld
until [ -f traces/tmpl_test.done ]; do sleep 30; done
venv/bin/python osw_run.py --system tfork --release-copies 1 --obs-timeout 600 --mem-limit-gib 220 --parallel 0 --tasks pfx_test_tasks.json \
  --rollouts 8 --replay traces/grpo_tfork16_e0 --setup-concurrency 2 --fork-concurrency 2 --overlay-rootfs 0 --prefix-cache pfx_cache \
  --prefix-save 0 --prefix-restore template --result-dir traces/pfx_C_tmpl2 > traces/pfx_C_tmpl2.log 2>&1; echo "C_tmpl2 rc=$?"
echo done > traces/tmpl_test2.done
