#!/bin/bash
# tfork replay with --tfork-overlay-btrfs (osw_run.py --overlay-rootfs 1), same recordings/settings as replay32_tfork
cd /mnt/ssd2/vikranth/osworld; T=$PWD/traces; R=$T/replay32_tfork_overlay
P="sudo env CONTAINERS_STORAGE_CONF=/mnt/btrfs/podman/storage.conf CONTAINERS_CONF=/mnt/ssd2/vikranth/osworld/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled >/dev/null
sudo rm -rf $R
sudo env DOUBAO_API_URL=http://127.0.0.1:1/v1 venv/bin/python osw_run.py --system tfork --overlay-rootfs 1 --tasks $PWD/grpo_batch32v2.json \
  --rollouts 8 --max-steps 15 --parallel 8 --replay $T/rec32v2_tfork --result-dir $R > $R.log 2>&1
$P ps -a --format "{{.Names}}" | xargs -r -n 20 $P rm -f >/dev/null 2>&1
sudo chown -R vikranth:vikranth $R $R.log; touch $R.done
