#!/bin/bash
# AENV replay over the direct path (no AENV HTTP proxy), same settings as replay31_{tfork,criu}
cd /mnt/ssd2/vikranth/osworld; T=$PWD/traces; R=$T/replay31_aenv_direct
KEY=$(sudo cat /mnt/ssd2/aenv/env/secrets/api-key)
sudo rm -rf $R
sudo env DOUBAO_API_URL=http://127.0.0.1:1/v1 venv/bin/python osw_run.py --system aenv --tasks /mnt/ssd2/vikranth/osworld/replay31.json \
  --rollouts 8 --max-steps 15 --parallel 8 --replay $T/osw_criu32_capped --result-dir $R > $R.log 2>&1
sudo chown -R vikranth:vikranth $R $R.log
for s in $(curl -fs -H "X-API-Key: $KEY" http://127.0.0.1:8000/sandboxes | python3 -c "import json,sys; [print(x['sandboxID']) for x in json.load(sys.stdin)]" 2>/dev/null); do
  curl -fs -X DELETE -H "X-API-Key: $KEY" http://127.0.0.1:8000/sandboxes/$s >/dev/null; done
sudo docker stop aenv-server >/dev/null; echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled >/dev/null
touch $R.done
