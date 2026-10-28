#!/bin/bash
cd /mnt/ssd2/vikranth/osworld
./compare.sh traces/rec32v2_tfork smoke2.json traces/smoke_clean tfork criu aenv -- --rollouts 2 --max-steps 3 --parallel 2
./compare.sh traces/rec32v2_tfork smoke2.json traces/smoke_clean_base tfork -- --rollouts 2 --max-steps 3 --parallel 2 --base-fork 1
touch traces/smoke_clean.done
