#!/bin/bash
cd /mnt/ssd2/vikranth/osworld
sudo rm -rf traces/replay3_tfork
sudo env DOUBAO_API_URL=http://127.0.0.1:1/v1 venv/bin/python osw_run.py --system tfork --tasks replay3.json --rollouts 8 --max-steps 15 \
  --parallel 0 --replay traces/osw_criu32_capped --result-dir traces/replay3_tfork > traces/replay3_tfork.log 2>&1
touch traces/replay3_tfork.done
