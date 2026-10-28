#!/bin/bash
cd /mnt/ssd2/vikranth/osworld
common="--system tfork --tasks basefork4.json --rollouts 8 --max-steps 5 --parallel 0"
for r in "bf4_tfork_base --base-fork 1" "bf4_tfork_plain"; do
  set -- $r; rm -rf traces/$1
  sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py $common --result-dir traces/$1 "${@:2}" > traces/$1.log 2>&1
done
touch traces/bf4.done
