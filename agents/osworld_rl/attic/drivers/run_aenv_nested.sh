#!/bin/bash
# Does AENV support fork-of-fork? --base-fork 1: one desktop -> fork 4 task sources -> setup -> fork 8 each. Replay mode (no model).
cd /mnt/ssd2/vikranth/osworld; T=$PWD/traces; R=$T/aenv_nested4
KEY=$(sudo cat /mnt/ssd2/aenv/env/secrets/api-key)
python3 -c "
import json; b = json.load(open('grpo_batch32v2.json'))
json.dump({d: b[d][:1] for d in ('chrome', 'gimp', 'libreoffice_calc', 'libreoffice_impress')}, open('nested4.json', 'w'))"
echo 0 | sudo tee /proc/sys/kernel/io_uring_disabled >/dev/null
sudo docker start aenv-server >/dev/null; for i in $(seq 90); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 2; done
sudo rm -rf $R
sudo env DOUBAO_API_URL=http://127.0.0.1:1/v1 venv/bin/python osw_run.py --system aenv --base-fork 1 --tasks $PWD/nested4.json \
  --rollouts 8 --max-steps 15 --parallel 0 --replay $T/rec32v2_tfork --result-dir $R > $R.log 2>&1
for s in $(curl -fs -H "X-API-Key: $KEY" http://127.0.0.1:8000/sandboxes | python3 -c "import json,sys; [print(x['sandboxID']) for x in json.load(sys.stdin)]" 2>/dev/null); do
  curl -fs -X DELETE -H "X-API-Key: $KEY" http://127.0.0.1:8000/sandboxes/$s >/dev/null; done
sudo docker stop aenv-server >/dev/null; echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled >/dev/null
sudo chown -R vikranth:vikranth $R $R.log; touch $R.done
