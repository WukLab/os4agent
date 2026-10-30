#!/bin/bash
# HOME=/home/user check: replay diff15 rollout 0 of VLC 8ba5ae7a (Tools > Preferences > Input/Codecs > Browse > Desktop > OK > Save), no model.
cd /mnt/ssd2/vikranth/osworld
rm -rf traces/home_vlc
env A11Y_REASON=1 A11Y_SCREENSHOT=1 venv/bin/python osw_run.py --system tfork --spec off --model replay --tasks vlc_rec.json --rollouts 1 --max-steps 15 \
  --replay traces/diff15_shot --replay-latency 0 --result-dir traces/home_vlc --parallel 0 --release-copies 1 --obs-timeout 600 > traces/home_vlc.log 2>&1
echo "rc=$?"
