#!/bin/bash
# prefix-cache test with tfork-restore: A no cache, B empty cache, C warm cache; replaying grpo_tfork16_e0
cd /mnt/ssd2/vikranth/osworld
COMMON="--system tfork --tasks pfx_test_tasks.json --rollouts 8 --replay traces/grpo_tfork16_e0 --release-copies 1 --obs-timeout 600 --setup-concurrency 2 --fork-concurrency 2 --mem-limit-gib 220"
venv/bin/python osw_run.py $COMMON --result-dir traces/pfx_A > traces/pfx_A.log 2>&1; echo "A rc=$?"
venv/bin/python osw_run.py $COMMON --result-dir traces/pfx_B --prefix-cache pfx_cache --prefix-clear 1 > traces/pfx_B.log 2>&1; echo "B rc=$?"
venv/bin/python osw_run.py $COMMON --result-dir traces/pfx_C --prefix-cache pfx_cache > traces/pfx_C.log 2>&1; echo "C rc=$?"
echo done > traces/pfx_test.done
