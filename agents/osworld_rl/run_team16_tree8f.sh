#!/bin/bash
# Live GRPO loop, epochs 0-5 (6 epochs), on the team's 16 tasks x 8 rollouts with the depth-8 tree cache as replay-tested
# -- as run_team16_tree8.sh but groups in task-file order (no --longest-first), to separate ordering from caching
# (run_tree8_same2.sh): --prefix-depth 8 --prefix-tree (leaf-first eviction, roots last) --prefix-policy gdsf
# --prefix-admit-cost 10 (path cost from the root) --prefix-lazy-start, shared clones, new saves evict only finished
# groups' non-root snapshots, 40 GiB, --clone-copies-limit 16, overlay 0, --no-stop, groups in task-file order.
# One cache for all epochs, started cold. Detached systemd unit.
# The pod is created with a start command that runs pod_serve.sh (vLLM with LoRA, GPU_UTIL=0.4); this script copies
# train_grpo.py to it, waits until vLLM serves, opens the tunnel :8100 -> pod :8000, then starts the loop.
# Compare with team16_tree8 (same, longest-first), team16_plazy (depth 2, plain lru, file order), team16_base (no cache).
#   POD=root@<ip> PORT=<ssh port> bash run_team16_tree8f.sh              -> traces/team16_tree8f_e*, pod_backup/team16_tree8f/
set -euo pipefail
cd "$(dirname "$0")"
HERE=$PWD; REPO="$(cd ../.. && pwd)"; POD=${POD:?root@ip}; PORT=${PORT:?ssh port}; EXP=team16_tree8f; KEY=$HOME/.ssh/runpod_wa
C=$HERE/traces/${EXP}_cache
PT="sudo -n env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf CONTAINERS_CONF=$HERE/containers-os4agent.conf $REPO/podman-tfork.sh"
[ ! -e traces/${EXP}_e0 ] || { echo "traces/${EXP}_e0 exists: not overwriting"; exit 1; }
[ "$($PT ps -aq | wc -l)" = 0 ] || { echo "containers are running: not starting (the cache starts cold)"; exit 1; }
sudo -n rm -rf "$C"
SSH=(ssh -i "$KEY" -o ServerAliveInterval=30 -o StrictHostKeyChecking=accept-new -p "$PORT" "$POD")
for i in $(seq 60); do "${SSH[@]}" true 2>/dev/null && break; sleep 10; done  # sshd comes up with the pod
"${SSH[@]}" "mkdir -p /root/osworld_rl"
rsync -a -e "ssh -i $KEY -o StrictHostKeyChecking=accept-new -p $PORT" train_grpo.py "$POD:/root/osworld_rl/"
st=""
for i in $(seq 120); do  # the start command installs vLLM (~2 min) and loads the model (~3 min)
    st=$("${SSH[@]}" "cat /root/serve.status 2>/dev/null" || true)
    [ "$st" = SERVING ] && break
    [ $((i % 6)) = 0 ] && echo "$(date +%T) waiting for vLLM: $("${SSH[@]}" "tail -1 /root/pod_serve.log /root/vllm.log 2>/dev/null | cut -c1-120" || true)"
    sleep 10
done
[ "$st" = SERVING ] || { echo "vLLM not serving after 20 min"; exit 1; }
curl -sf localhost:8100/v1/models >/dev/null || ssh -f -N -i "$KEY" -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
    -p "$PORT" -L 8100:localhost:8000 "$POD"
curl -sf localhost:8100/v1/models >/dev/null || { echo "vLLM not reachable on :8100 (tunnel)"; exit 1; }
sudo -n systemd-run --unit=osw-$EXP --collect --uid="$(id -u)" --gid="$(id -g)" -p WorkingDirectory=$HERE \
    -p StandardOutput=file:$HERE/traces/${EXP}_loop.log -p StandardError=file:$HERE/traces/${EXP}_loop.log \
    --setenv=HOME=$HOME --setenv=PATH=/usr/local/bin:/usr/bin:/bin --setenv=PWD=$HERE \
    $HERE/venv/bin/python -I $HERE/osw_loop.py --exp $EXP --system tfork --epochs 6 \
    --tasks $HERE/grpo_batch16_team.json --rollouts 8 --no-stop \
    --run-args "--parallel 8 --os4agent $REPO --storage-conf /mnt/data/btrfs/podman/storage.conf --overlay-rootfs 0 --clone-copies-limit 16 --prefix-cache $C --prefix-depth 8 --prefix-mem --prefix-lazy --prefix-lazy-start --prefix-tree --prefix-policy gdsf --prefix-admit-cost 10 --prefix-mem-budget-gib 40" \
    --pod "$POD" --pod-port "$PORT" --pod-key "$KEY"
echo "launched osw-$EXP $(date +%T); log traces/${EXP}_loop.log"
