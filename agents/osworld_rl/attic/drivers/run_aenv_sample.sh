set -x; cd /mnt/ssd2/vikranth/osworld; T=/mnt/ssd2/vikranth/osworld/traces
python3 - <<'PY'
import json
b = json.load(open("grpo_batch29.json"))
s = {"chrome": ["bb5e4c0d-f964-439c-97b6-bdb9747de3f4"], "libreoffice_calc": ["4e6fcf72-daf3-439f-a232-c434ce416af6"],
     "libreoffice_impress": [b["libreoffice_impress"][0]], "gimp": [b["gimp"][0]]}
json.dump(s, open("aenv_sample.json", "w"), indent=1); print(s)
PY
echo 0 | sudo tee /proc/sys/kernel/io_uring_disabled
sudo docker start aenv-server; for i in $(seq 90); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 2; done
K=$(sudo cat /mnt/ssd2/aenv/env/secrets/api-key)
sweep() { for s in $(curl -s -H "X-API-Key: $K" http://127.0.0.1:8000/sandboxes | python3 -c "import json,sys; [print(x['sandboxID']) for x in json.load(sys.stdin)]"); do curl -s -X DELETE -H "X-API-Key: $K" http://127.0.0.1:8000/sandboxes/$s >/dev/null; done; }
sweep
R=$T/aenv_sample; sudo rm -rf $R
sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system aenv --model qwen3vl8b \
  --tasks /mnt/ssd2/vikranth/osworld/aenv_sample.json --rollouts 8 --max-steps 15 --parallel 0 --result-dir $R > $R.log 2>&1
sudo chown -R vikranth:vikranth $R $R.log
sweep; sudo docker stop aenv-server; echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled
echo DONE > $T/aenv_sample.done
