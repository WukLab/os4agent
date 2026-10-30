#!/bin/bash
# 5-epoch GRPO, tfork + prefix cache (overlay off); same settings as grpo_tfork16 otherwise. Writes grpo_pfx.done at the end.
cd /mnt/ssd2/vikranth/osworld
venv/bin/python osw_loop.py --exp grpo_tfork16_pfx --system tfork --epochs 5 --minibatches 1 --keep-going --prefix-save-epochs 1 \
  --pod-key /home/vikranth/.ssh/runpod_wa --pod root@103.207.149.80 --pod-port 16484 \
  --run-args "--groups 16 --parallel 0 --release-copies 1 --obs-timeout 600 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220 --prefix-cache pfx_grpo --overlay-rootfs 0"
echo "rc=$?" > grpo_pfx.done
