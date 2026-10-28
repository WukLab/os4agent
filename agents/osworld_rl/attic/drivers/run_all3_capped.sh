#!/bin/bash
# Memory comparison, one rollout epoch per system (no training): 32 tasks x 8 rollouts, all groups run concurrently, at most
# --fork-concurrency (default 4) groups forking at once. Order: AENV (server already up) -> CRIU (CKPT, no CoW) -> tfork.
set -x; cd /mnt/ssd2/vikranth/osworld; T=/mnt/ssd2/vikranth/osworld/traces
P="sudo env CONTAINERS_STORAGE_CONF=/mnt/btrfs/podman/storage.conf CONTAINERS_CONF=/mnt/ssd2/vikranth/osworld/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
A=$HOME/.local/bin/aenv
clean() { $P ps -a --format "{{.Names}}" | xargs -r -n 20 $P rm -f >/dev/null 2>&1; }
run() {
  local R=$T/$2; sudo rm -rf $R
  sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system $1 --model qwen3vl8b \
    --tasks /mnt/ssd2/vikranth/osworld/grpo_batch32.json --rollouts 8 --max-steps 15 --parallel 0 --result-dir $R "${@:3}" > $R.log 2>&1
  sudo chown -R vikranth:vikranth $R $R.log
}
echo 0 | sudo tee /proc/sys/kernel/io_uring_disabled
sudo docker start aenv-server; for i in $(seq 90); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 2; done
run aenv osw_aenv32_capped
for s in $($A ls 2>/dev/null | python3 -c "import json,sys; [print(x[\"sandboxID\"]) for x in json.load(sys.stdin)]" 2>/dev/null); do $A rm $s; done
sudo docker stop aenv-server; echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled
run criu osw_criu32_capped --full-memcopy 1 --save-ckpt /mnt/btrfs/osw_ckpts; clean
run tfork osw_tfork32_capped; clean
echo DONE > $T/all3_capped.done
