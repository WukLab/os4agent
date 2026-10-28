#!/bin/bash
cd /mnt/ssd2/vikranth/osworld; T=traces; K=$(sudo cat /mnt/ssd2/aenv/env/secrets/api-key)
sweep() { for s in $(curl -s -H "X-API-Key: $K" http://127.0.0.1:8000/sandboxes | python3 -c "import json,sys; [print(x['sandboxID']) for x in json.load(sys.stdin)]"); do curl -s -X DELETE -H "X-API-Key: $K" http://127.0.0.1:8000/sandboxes/$s >/dev/null; done; }
sweep; R=$T/aenv_failed_rerun; sudo rm -rf $R $R.log
sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system aenv --model qwen3vl8b \
  --tasks /mnt/ssd2/vikranth/osworld/aenv_failed.json --rollouts 8 --max-steps 15 --parallel 0 --result-dir $R > $R.log 2>&1
sudo chown -R vikranth:vikranth $R $R.log; sweep; sudo docker stop aenv-server; echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled
echo DONE > $T/aenv_failed_rerun.done
