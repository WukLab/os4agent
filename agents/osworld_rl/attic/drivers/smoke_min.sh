#!/bin/bash
cd /mnt/ssd2/vikranth/osworld
./compare.sh traces/rec32v2_tfork attic/batches/smoke2.json traces/smoke_min tfork -- --limit 1 --rollouts 2 --max-steps 2
touch traces/smoke_min.done
