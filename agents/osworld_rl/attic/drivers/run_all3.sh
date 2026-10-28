#!/bin/bash
# One epoch of rollouts (no training) per system for the memory comparison: 32 tasks x 8 rollouts, all groups at once.
# Order: CRIU (CKPT, no CoW) -> tfork -> AENV. Systems never overlap. Results: traces/osw_<system>32_once/{mem,events}.jsonl
set -x; cd /mnt/ssd2/vikranth/osworld; T=/mnt/ssd2/vikranth/osworld/traces
P="sudo env CONTAINERS_STORAGE_CONF=/mnt/btrfs/podman/storage.conf CONTAINERS_CONF=/mnt/ssd2/vikranth/osworld/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
clean() { $P ps -a --format "{{.Names}}" | xargs -r -n 20 $P rm -f >/dev/null 2>&1; }
run() {   # run <system> <result-name> [extra osw_run args]
  local R=$T/$2; sudo rm -rf $R
  sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system $1 --model qwen3vl8b \
    --tasks /mnt/ssd2/vikranth/osworld/grpo_batch32.json --rollouts 8 --max-steps 15 --parallel 0 --result-dir $R "${@:3}" > $R.log 2>&1
  sudo chown -R vikranth:vikranth $R $R.log; echo "$2 rc=$?"
}
echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled
run criu  osw_criu32_once  --full-memcopy 1 --save-ckpt /mnt/btrfs/osw_ckpts; clean
run tfork osw_tfork32_once; clean
# ---- AENV: io_uring on, server up, template from the current image, smoke test, full run
echo 0 | sudo tee /proc/sys/kernel/io_uring_disabled
sudo docker start aenv-server; for i in $(seq 90); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 2; done
A=$HOME/.local/bin/aenv
$A template rm kde-osworld || true
$A pull 172.17.0.1:5005/webtop:ubuntu-kde-osworld --name kde-osworld --timeout 3600
run aenv smoke_aenv --limit 1 --rollouts 2 --max-steps 3
if grep -q "\"event\": \"rollout_done\"" $T/smoke_aenv/events.jsonl 2>/dev/null; then run aenv osw_aenv32_once; else echo "AENV smoke failed; skipping full AENV run"; fi
for s in $($A ls 2>/dev/null | python3 -c "import json,sys; [print(x[\"sandboxID\"]) for x in json.load(sys.stdin)]" 2>/dev/null); do $A rm $s; done
sudo docker stop aenv-server; echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled
echo ALL3 DONE > $T/all3.done
