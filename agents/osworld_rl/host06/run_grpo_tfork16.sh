#!/bin/bash
# waits for container internet (DOCKER-USER rules), then runs the 10-epoch GRPO loop; writes grpo_tfork16.done at the end
cd /mnt/ssd2/vikranth/osworld
rm -f grpo_tfork16.done
P="env CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
t0=$(date +%s)
until [ "$($P run --rm --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "curl -s -m 10 -o /dev/null -w %{http_code} https://www.google.com" 2>/dev/null | tail -c 3)" = 200 ]; do
  [ $(( $(date +%s) - t0 )) -gt 2700 ] && { echo "no internet after 45 min, giving up"; echo nonet > grpo_tfork16.done; exit 1; }
  echo "$(date +%T) waiting for container internet"; sleep 30
done
echo "internet ok, starting loop"
venv/bin/python osw_loop.py --exp grpo_tfork16 --system tfork --epochs 10 --minibatches 1 --keep-going --pod-key /home/vikranth/.ssh/runpod_wa --pod root@213.181.105.210 --pod-port 12241 --run-args "--groups 16 --parallel 0 --release-copies 1 --obs-timeout 600 --setup-concurrency 16 --fork-concurrency 4 --mem-limit-gib 220"
echo "rc=$?" > grpo_tfork16.done
