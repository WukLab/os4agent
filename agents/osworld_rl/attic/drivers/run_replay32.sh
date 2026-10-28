#!/bin/bash
# Memory comparison by replay, full batch: every system re-executes traces/rec32v2_tfork (32 tasks x 8 rollouts, grpo_batch32v2:
# no thunderbird / vs_code / os), no model calls, at most 8 task groups live and 4 forking at once. tfork -> CRIU (no CoW) -> AENV
# (direct path to the VMs, see osw_run.py Forwarder).
set -x; cd /mnt/ssd2/vikranth/osworld; T=/mnt/ssd2/vikranth/osworld/traces
P="sudo env CONTAINERS_STORAGE_CONF=/mnt/btrfs/podman/storage.conf CONTAINERS_CONF=/mnt/ssd2/vikranth/osworld/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
KEY=$(sudo cat /mnt/ssd2/aenv/env/secrets/api-key)
clean() { $P ps -a --format "{{.Names}}" | xargs -r -n 20 $P rm -f >/dev/null 2>&1; }
aenv_clean() {
  for s in $(curl -fs -H "X-API-Key: $KEY" http://127.0.0.1:8000/sandboxes | python3 -c "import json,sys; [print(x['sandboxID']) for x in json.load(sys.stdin)]" 2>/dev/null); do
    curl -fs -X DELETE -H "X-API-Key: $KEY" http://127.0.0.1:8000/sandboxes/$s >/dev/null; done
}
run() {
  local R=$T/$2; sudo rm -rf $R
  sudo env DOUBAO_API_URL=http://127.0.0.1:1/v1 venv/bin/python osw_run.py --system $1 --tasks /mnt/ssd2/vikranth/osworld/grpo_batch32v2.json \
    --rollouts 8 --max-steps 15 --parallel 8 --replay $T/rec32v2_tfork --result-dir $R "${@:3}" > $R.log 2>&1
  sudo chown -R vikranth:vikranth $R $R.log
}
echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled
run tfork replay32_tfork; clean
run criu replay32_criu --full-memcopy 1; clean
echo 0 | sudo tee /proc/sys/kernel/io_uring_disabled
sudo docker start aenv-server; for i in $(seq 90); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 2; done
run aenv replay32_aenv; aenv_clean
sudo docker stop aenv-server; echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled
echo DONE > $T/replay32_all3.done
