#!/bin/bash
# One clean epoch of rollouts (no training) for the CRIU baseline memory profile: 32 tasks x 8 rollouts, all groups at once.
cd /mnt/ssd2/vikranth/osworld; T=/mnt/ssd2/vikranth/osworld/traces
while pgrep -f "[o]sw_run.py --system criu" >/dev/null; do sleep 30; done   # let the current epoch finish
R=$T/osw_criu32_once; sudo rm -rf $R
sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system criu --model qwen3vl8b \
  --tasks /mnt/ssd2/vikranth/osworld/grpo_batch32.json --rollouts 8 --max-steps 15 --parallel 0 --full-memcopy 1 \
  --save-ckpt /mnt/btrfs/osw_ckpts --result-dir $R > $R.log 2>&1
sudo chown -R vikranth:vikranth $R $R.log; echo DONE > $T/osw_criu32_once.done
