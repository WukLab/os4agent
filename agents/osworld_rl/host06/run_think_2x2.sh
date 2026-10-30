#!/bin/bash
# GRPO sanity check, Thinking + LoRA, 16 tasks x 8 rollouts: 2 regular epochs (grpo_think_reg), then 2 speculation epochs
# (grpo_think_spec: TAGE top-2 forks from step 3 while < 64 rollouts live, <= 10 clones at once, TAGE warmed only from
# this run's earlier epochs). Both start from the base model. Writes run_think_2x2.done at the end.
cd /mnt/ssd2/vikranth/osworld
rm -f run_think_2x2.done
export A11Y_REASON=1 A11Y_THINK_BUDGET=1024
P="env CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
until [ "$($P run --rm --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "curl -s -m 10 -o /dev/null -w %{http_code} https://www.google.com" 2>/dev/null | tail -c 3)" = 200 ]; do
  echo "$(date +%T) waiting for container internet"; sleep 30
done
COMMON="--system tfork --epochs 2 --keep-going --pod-key /home/vikranth/.ssh/runpod_wa --pod root@64.247.201.57 --pod-port 19413 \
  --base Qwen/Qwen3-VL-8B-Thinking --base-served qwen3vl8b-think --train-args=--max-len=8192"
RUN="--groups 16 --parallel 0 --release-copies 1 --obs-timeout 600 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220"
venv/bin/python osw_loop.py --exp grpo_think_reg $COMMON --run-args "$RUN"; echo "reg rc=$?"
venv/bin/python osw_loop.py --exp grpo_think_spec $COMMON --spec-warm-own \
  --run-args "$RUN --spec-exec 2 --spec-from 3 --spec-below 64 --spec-max-forks 10"; echo "spec rc=$?"
echo done > run_think_2x2.done
