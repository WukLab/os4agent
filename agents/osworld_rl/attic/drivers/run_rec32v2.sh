#!/bin/bash
# Record trajectories for the full replay comparison: live tfork run, base model, grpo_batch32v2 (32 tasks, no thunderbird/vs_code/os)
cd /mnt/ssd2/vikranth/osworld; R=$PWD/traces/rec32v2_tfork
sudo rm -rf $R
sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system tfork --model qwen3vl8b \
  --tasks /mnt/ssd2/vikranth/osworld/grpo_batch32v2.json --rollouts 8 --max-steps 15 --parallel 8 --result-dir $R > $R.log 2>&1
sudo chown -R vikranth:vikranth $R $R.log
P="sudo env CONTAINERS_STORAGE_CONF=/mnt/btrfs/podman/storage.conf CONTAINERS_CONF=/mnt/ssd2/vikranth/osworld/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
$P ps -a --format "{{.Names}}" | xargs -r -n 20 $P rm -f >/dev/null 2>&1
touch $R.done
