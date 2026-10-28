#!/bin/bash
cd /mnt/ssd2/vikranth/osworld; T=traces
sudo rm -rf $T/replay3_aenv_direct
sudo env DOUBAO_API_URL=http://127.0.0.1:1/v1 venv/bin/python osw_run.py --system aenv --tasks replay3.json --rollouts 8 --max-steps 15 \
  --parallel 0 --replay $PWD/$T/osw_criu32_capped --result-dir $T/replay3_aenv_direct > $T/replay3_aenv_direct.log 2>&1
touch $T/replay3_aenv_direct.done
