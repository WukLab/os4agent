#!/bin/bash
# AENV rerun for the 29-task memory comparison, after run_all3_29.sh (CRIU, tfork) finishes. Cleanup via the API: `aenv ls` misses API-created sandboxes.
set -x; cd /mnt/ssd2/vikranth/osworld; T=/mnt/ssd2/vikranth/osworld/traces
until [ -f $T/all3_29.done ]; do sleep 60; done
echo 0 | sudo tee /proc/sys/kernel/io_uring_disabled
sudo docker start aenv-server; for i in $(seq 90); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 2; done
K=$(sudo cat /mnt/ssd2/aenv/env/secrets/api-key)
sweep() { for s in $(curl -s -H "X-API-Key: $K" http://127.0.0.1:8000/sandboxes | python3 -c "import json,sys; [print(x['sandboxID']) for x in json.load(sys.stdin)]"); do curl -s -X DELETE -H "X-API-Key: $K" http://127.0.0.1:8000/sandboxes/$s >/dev/null; done; }
sweep
R=$T/osw_aenv29; sudo mv $R ${R}_crashed_emfile 2>/dev/null; sudo mv $R.log ${R}_crashed_emfile.log 2>/dev/null
sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system aenv --model qwen3vl8b \
  --tasks /mnt/ssd2/vikranth/osworld/grpo_batch29.json --rollouts 8 --max-steps 15 --parallel 0 --result-dir $R > $R.log 2>&1
sudo chown -R vikranth:vikranth $R $R.log
sweep; sudo docker stop aenv-server; echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled
echo DONE > $T/aenv29.done
