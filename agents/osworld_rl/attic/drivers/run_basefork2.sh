#!/bin/bash
cd /mnt/ssd2/vikranth/osworld
while [ ! -f traces/bf4.done ]; do sleep 20; done
rm -rf traces/bf4_tfork_base
sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system tfork --tasks basefork4.json --rollouts 8 --max-steps 5 --parallel 0 --result-dir traces/bf4_tfork_base --base-fork 1 > traces/bf4_tfork_base.log 2>&1
touch traces/bf4b.done
