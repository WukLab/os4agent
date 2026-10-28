#!/bin/bash
# after replay32_all3: (1) tfork first-wave repro with failed-clone restore logs kept, (2) AENV rerun of the group dropped by pairing
set -x; cd /mnt/ssd2/vikranth/osworld; T=$PWD/traces
while [ ! -f $T/replay32_all3.done ]; do sleep 30; done
KEY=$(sudo cat /mnt/ssd2/aenv/env/secrets/api-key)
P="sudo env CONTAINERS_STORAGE_CONF=/mnt/btrfs/podman/storage.conf CONTAINERS_CONF=/mnt/ssd2/vikranth/osworld/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled
R=$T/tfork_wave1_repro; sudo rm -rf $R
sudo env DOUBAO_API_URL=http://127.0.0.1:1/v1 venv/bin/python osw_run.py --system tfork --tasks $PWD/grpo_batch32v2.json --limit 8 \
  --rollouts 8 --max-steps 15 --parallel 8 --replay $T/rec32v2_tfork --result-dir $R > $R.log 2>&1
$P ps -a --format "{{.Names}}" | xargs -r -n 20 $P rm -f >/dev/null 2>&1
python3 -c "import json; json.dump({'$(python3 -c "import json; b=json.load(open('grpo_batch32v2.json')); print([d for d,ids in b.items() if '9f935cce-0a9f-435f-8007-817732bfc0a5' in ids][0])")': ['9f935cce-0a9f-435f-8007-817732bfc0a5']}, open('aenv_rerun1.json','w'))"
echo 0 | sudo tee /proc/sys/kernel/io_uring_disabled
sudo docker start aenv-server; for i in $(seq 90); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 2; done
R=$T/replay32_aenv_rerun1; sudo rm -rf $R
sudo env DOUBAO_API_URL=http://127.0.0.1:1/v1 venv/bin/python osw_run.py --system aenv --tasks $PWD/aenv_rerun1.json \
  --rollouts 8 --max-steps 15 --parallel 8 --replay $T/rec32v2_tfork --result-dir $R > $R.log 2>&1
for s in $(curl -fs -H "X-API-Key: $KEY" http://127.0.0.1:8000/sandboxes | python3 -c "import json,sys; [print(x['sandboxID']) for x in json.load(sys.stdin)]" 2>/dev/null); do
  curl -fs -X DELETE -H "X-API-Key: $KEY" http://127.0.0.1:8000/sandboxes/$s >/dev/null; done
sudo docker stop aenv-server; echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled
sudo chown -R vikranth:vikranth $T/tfork_wave1_repro* $T/replay32_aenv_rerun1*
touch $T/followup.done
