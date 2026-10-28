#!/bin/bash
# After the CKPT runs: switch the host to AENV mode, rebuild the kde-osworld template from the current image, smoke-test osw_run
# --system aenv end to end, then switch back (io_uring off, aenv-server stopped) so tfork/CRIU keep working.
set -x; cd /mnt/ssd2/vikranth/osworld; T=traces
until [ -f $T/prof_ckpt.done ]; do sleep 60; done
cp osw_run_next.py osw_run.py
echo 0 | sudo tee /proc/sys/kernel/io_uring_disabled
sudo docker start aenv-server; for i in $(seq 90); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 2; done
A=$HOME/.local/bin/aenv
$A template rm kde-osworld || true
$A pull 172.17.0.1:5005/webtop:ubuntu-kde-osworld --name kde-osworld --timeout 3600
$A template ls | python3 -c "import json,sys; [print(t[\"names\"], t[\"buildStatus\"]) for t in json.load(sys.stdin)]"
sudo rm -rf $T/smoke_aenv
sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system aenv --limit 1 --rollouts 2 --max-steps 3 \
  --result-dir $T/smoke_aenv > $T/smoke_aenv.log 2>&1; echo "smoke rc=$?"
sudo chown -R vikranth:vikranth $T/smoke_aenv $T/smoke_aenv.log
for s in $($A ls 2>/dev/null | python3 -c "import json,sys; [print(x[\"sandboxID\"]) for x in json.load(sys.stdin)]" 2>/dev/null); do $A rm $s; done
sudo docker stop aenv-server; echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled
echo AENV DONE > $T/aenv_smoke.done
