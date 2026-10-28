#!/bin/bash
# Stock-CRIU profiling: full batch, 8 rollouts x 15 steps, speculation off then on (TAGE top-8, shadow).
cd /mnt/ssd2/vikranth/osworld; T=/mnt/ssd2/vikranth/osworld/traces
for spec in off tage; do
  R=$T/prof_criu_spec_$spec; sudo rm -rf $R
  sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system criu --spec $spec --spec-topk 8 \
    --rollouts 8 --max-steps 15 --result-dir $R > $R.log 2>&1
  sudo chown -R vikranth:vikranth $R $R.log
done
echo ALL DONE >> $T/prof_criu.done
