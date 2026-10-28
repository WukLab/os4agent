#!/usr/bin/env bash
# Run ON 02 once the tunnel is up. Usage: run_02.sh <run_name> [extra OSWorld run args]
# Traces land in $WUK_ROOT/traces/<run_name>/ : llm.jsonl (per-request timing + batch size), vllm_metrics.jsonl (1 Hz batch/queue),
# OSWorld's own results/<task>/traj.jsonl + recording.mp4 + step screenshots (full replay).
HERE=$(cd "$(dirname "$0")" && pwd); set -e; SERVED0=$SERVED; source "$HERE/.env"; SERVED=${SERVED0:-$SERVED}; source "$WUK_ROOT/docker.env"; N=$1; shift   # SERVED0: keep the caller's SERVED (grpo_loop passes pol<e>)
T=$WUK_ROOT/traces/$N; mkdir -p $T; cd $WUK_ROOT/OSWorld
curl -sf localhost:$LLM_PORT/v1/models >/dev/null || { echo "tunnel down: nothing on 02:$LLM_PORT"; exit 1; }
LLM_PORT=$LLM_PORT PROXY_PORT=$PROXY_PORT nohup ../venv/bin/python $HERE/proxy.py $T > $T/proxy.log 2>&1 &
export VM_STORAGE_DIR=${VM_STORAGE_DIR:-$WUK_ROOT/vm_storage}; mkdir -p $VM_STORAGE_DIR   # see patch_storage.py
# podman (02, rootless: only our containers) or system docker (06: only OSWorld VMs, but note this also hits other users' OSWorld VMs)
trap "kill $!; podman rm -f -a >/dev/null 2>&1 || docker ps -aq --filter ancestor=happysixd/osworld-docker | xargs -r docker rm -f >/dev/null; docker run --rm --entrypoint sh -v $VM_STORAGE_DIR:/s happysixd/osworld-docker -c 'rm -rf /s/*' >/dev/null 2>&1" EXIT
export AWS_REGION=us-east-1 AWS_SUBNET_ID=x AWS_SECURITY_GROUP_ID=x  # runner imports the aws manager even for docker; values unused
export DOUBAO_API_URL=http://127.0.0.1:$PROXY_PORT/v1 DOUBAO_API_KEY=x   # OSWorld's UI-TARS agent reads these
PYTHONPATH=. timeout ${TIMEOUT:-0} ../venv/bin/python scripts/python/run_multienv_uitars15_v1.py --provider_name docker --headless \
  --observation_type screenshot_a11y_tree --model ${SERVED:-uitars15-7b} --max_steps ${MAX_STEPS:-15} --num_envs ${NUM_ENVS:-4} --result_dir $T/results \
  --test_all_meta_path evaluation_examples/${TASKS:-test_small.json} "$@" 2>&1 | tee $T/run.log
