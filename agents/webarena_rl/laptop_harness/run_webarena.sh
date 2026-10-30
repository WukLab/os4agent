#!/usr/bin/env bash
# Run ON 06 once the tunnel is up (same contract as osworld_rl/run_02.sh). Usage: run_webarena.sh <run_name>
# Traces land in $WA_ROOT/traces/<run_name>/ : llm.jsonl (per-request timing + batch size), vllm_metrics.jsonl (1 Hz batch/queue),
# results/webarena/a11y/<model>/shopping/<task>__g<k>/ (chat.jsonl, result.txt, traj.jsonl, per-step png/a11y/html snapshots, HAR, video).
HERE=$(cd "$(dirname "$0")" && pwd); set -e; SERVED0=$SERVED; source "$HERE/.env"; SERVED=${SERVED0:-$SERVED}; N=$1; shift
T=$WA_ROOT/traces/$N; mkdir -p $T; cd $WA_ROOT
curl -sf localhost:$LLM_PORT/v1/models >/dev/null || { echo "tunnel down: nothing on 06:$LLM_PORT"; exit 1; }
LLM_PORT=$LLM_PORT PROXY_PORT=$PROXY_PORT nohup venv/bin/python $HERE/proxy.py $T > $T/proxy.log 2>&1 &
PROXY=$!; trap "kill $PROXY; ${PODMAN:-sudo env CONTAINERS_STORAGE_CONF=/mnt/ssd2/podman/storage.conf podman} ps -a --format '{{.Names}}' | grep '^wa-shop-' | xargs -r ${PODMAN:-sudo env CONTAINERS_STORAGE_CONF=/mnt/ssd2/podman/storage.conf podman} rm -f -t 0 >/dev/null" EXIT
sleep 1
cd $HERE && timeout ${TIMEOUT:-0} $WA_ROOT/venv/bin/python wa_run.py --result_dir $T/results --model ${SERVED:-qwen3vl8b} \
  --tasks ${TASKS:-webarena_batch.json} --num_envs ${NUM_ENVS:-8} --max_steps ${MAX_STEPS:-30} "$@" 2>&1 | tee $T/run.log
