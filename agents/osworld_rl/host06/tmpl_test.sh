#!/bin/bash
# prefix cache with template restore: 2-task correctness check, then 4 replays of grpo_tfork16_pfx_e1 under full load
cd /mnt/ssd2/vikranth/osworld
S="--system tfork --release-copies 1 --obs-timeout 600 --mem-limit-gib 220 --parallel 0"
venv/bin/python osw_run.py $S --tasks pfx_test_tasks.json --rollouts 8 --replay traces/grpo_tfork16_e0 --setup-concurrency 2 --fork-concurrency 2 \
  --overlay-rootfs 0 --prefix-cache pfx_cache --prefix-save 0 --prefix-restore template --result-dir traces/pfx_C_tmpl > traces/pfx_C_tmpl.log 2>&1; echo "C_tmpl rc=$?"
L="$S --groups 16 --rollouts 8 --replay traces/grpo_tfork16_pfx_e1 --setup-concurrency 16 --fork-concurrency 4"
venv/bin/python osw_run.py $L --overlay-rootfs 1 --result-dir traces/ld_nocache_ov1 > traces/ld_nocache_ov1.log 2>&1; echo "nocache_ov1 rc=$?"
venv/bin/python osw_run.py $L --overlay-rootfs 0 --result-dir traces/ld_nocache_ov0 > traces/ld_nocache_ov0.log 2>&1; echo "nocache_ov0 rc=$?"
venv/bin/python osw_run.py $L --overlay-rootfs 0 --prefix-cache pfx_grpo --prefix-save 0 --prefix-restore disk --result-dir traces/ld_disk > traces/ld_disk.log 2>&1; echo "disk rc=$?"
venv/bin/python osw_run.py $L --overlay-rootfs 0 --prefix-cache pfx_grpo --prefix-save 0 --prefix-restore template --result-dir traces/ld_tmpl > traces/ld_tmpl.log 2>&1; echo "tmpl rc=$?"
echo done > traces/tmpl_test.done
