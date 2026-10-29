#!/bin/bash
# Smoke test of spec execution and the prefix cache on wuklab-08 (tfork), the model on a RunPod pod.
#   POD=root@<ip> PORT=<ssh port> bash smoke_wuklab08.sh <stage>
# stages, in order:
#   tunnel   local :8100 -> the pod's vLLM :8000 (8000 here is aenv-server's)
#   live     live recording, both features off: 2 tasks x 2 rollouts             -> traces/smoke_live
#   control  replay of it, both features off (the noise floor of a replay)         -> traces/smoke_control
#   spec     replay of it with --spec-exec 2 (the predictor starts empty)          -> traces/smoke_spec
#   spec_warm  the same, the predictor and action book first learn the recording -> traces/smoke_spec_warm
#            (it knows the replayed actions: an upper bound on hits, the most adoptions to check)
#   prefix   two replays of it sharing one --prefix-cache (depth 2): the 2nd hits  -> traces/smoke_prefix{1,2}
#   loop     osw_loop.py, 2 epochs x 2 tasks x 4 rollouts, both features on        -> traces/smoke_loop_e{0,1}
#   uncache  remove the prefix caches' saved clones (stopped containers) and indexes
# Replays and the loop run with --overlay-rootfs 0 (the prefix cache needs it; the rest match it). POD / PORT are
# needed only for tunnel / live / loop.
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(cd ../.. && pwd)"; POD=${POD:-}; PORT=${PORT:-}; KEY=$HOME/.ssh/runpod_wa
HOSTARGS="--os4agent $REPO --storage-conf /mnt/data/btrfs/podman/storage.conf"
TASKS=smoke_noweb2.json
REPLAY="--rollouts 2 --parallel 2 --replay traces/smoke_live --overlay-rootfs 0"
PT="sudo -n env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf $REPO/podman-tfork.sh"
uncache() {   # prefix-cache dir: its saved clones are stopped containers that outlive the run
    [ -f "$1/index.json" ] && venv/bin/python -I -c "import json,sys; [print(e['clone']) for e in json.load(open(sys.argv[1])).values() if e and 'clone' in e]" "$1/index.json" \
        | xargs -r $PT rm -f -t 0 >/dev/null
    sudo -n rm -rf "$1"
}
run() {   # result dir, osw_run.py args...
    d=traces/$1; shift
    sudo -n rm -rf "$d"
    echo "$(date +%T) $d: $*"
    sudo -n env DOUBAO_API_URL=http://127.0.0.1:8100/v1 DOUBAO_API_KEY=x venv/bin/python osw_run.py --system tfork \
        --tasks $TASKS $HOSTARGS --result-dir "$d" "$@" > "$d.log" 2>&1 || echo "osw_run exited $?"
    sudo -n chown -R "$(id -u):$(id -g)" "$d" "$d.log"
    venv/bin/python -I analyze.py progress "$d" 2>&1 | tail -4 || true
}
case $1 in
tunnel)
    curl -sf localhost:8100/v1/models >/dev/null && { echo "tunnel up"; exit 0; }
    : "${POD:?root@ip}" "${PORT:?ssh port}"
    ssh -i "$KEY" -f -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L 8100:localhost:8000 -p "$PORT" "$POD"
    curl -sf localhost:8100/v1/models ;;
live)   run smoke_live --rollouts 2 --parallel 2 ;;
control) run smoke_control $REPLAY ;;
spec)   run smoke_spec $REPLAY --spec-exec 2 ;;
spec_warm) run smoke_spec_warm $REPLAY --spec-exec 2 --spec-warm traces/smoke_live ;;
prefix)
    uncache traces/smoke_pcache
    run smoke_prefix1 $REPLAY --prefix-cache traces/smoke_pcache --prefix-depth 2
    run smoke_prefix2 $REPLAY --prefix-cache traces/smoke_pcache --prefix-depth 2
    echo "cache: $(venv/bin/python -I -c "import json; print(len(json.load(open('traces/smoke_pcache/index.json'))))" 2>/dev/null) entries" ;;
loop)
    : "${POD:?root@ip}" "${PORT:?ssh port}"
    uncache traces/smoke_lcache
    venv/bin/python -I osw_loop.py --exp smoke_loop --system tfork --epochs 2 --tasks $TASKS --rollouts 4 \
        --run-args "--parallel 2 $HOSTARGS --overlay-rootfs 0 --spec-exec 2 --prefix-cache traces/smoke_lcache --prefix-depth 2" \
        --pod "$POD" --pod-port "$PORT" --pod-key "$KEY" ;;
uncache) uncache traces/smoke_pcache; uncache traces/smoke_lcache ;;
*) echo "unknown stage $1"; exit 1 ;;
esac
