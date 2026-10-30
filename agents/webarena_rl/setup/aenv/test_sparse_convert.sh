#!/usr/bin/env bash
# Check the patched server's conversion (sparse RW layer, agentenv-v0.2.4-sparse-convert.patch) on a small image before
# the WebArena template: push alpine:3.22 to the local registry, `aenv pull` it as alpine-sparse-test (a fresh
# conversion: not in the cache), start a sandbox, run a command, write a file, fork it once, read the file in the copy.
#   bash agents/webarena_rl/setup/aenv/test_sparse_convert.sh      (after start-server.sh with the patched image)
set -euo pipefail
cd "$(dirname "$0")"
A=$HOME/.local/bin/aenv; KEY=$(cat .api-key); URL=http://127.0.0.1:8000
RC=$(docker exec aenv-server sh -c 'command -v regctl || ls /workspace/env/deps/regctl/*/regctl | tail -1')
docker exec aenv-server "$RC" registry set --tls disabled aenv-registry:5000
docker tag alpine:3.22 127.0.0.1:5005/alpine:3.22 && docker push -q 127.0.0.1:5005/alpine:3.22
"$A" template ls | grep -q alpine-sparse-test && "$A" template delete alpine-sparse-test
time "$A" pull aenv-registry:5000/alpine:3.22 --name alpine-sparse-test --timeout 600
SB=$("$A" start alpine-sparse-test --detach | grep -oE "[A-Za-z0-9_-]{8,}" | tail -1)
"$A" exec "$SB" sh -c 'cat /etc/alpine-release; df -h / | tail -1; echo hello > /root/f'
K=$(curl -fsS -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{"count": 1, "timeout": 600}' \
    "$URL/sandboxes/$SB/fork" | python3 -I -c "import json,sys; print(json.load(sys.stdin)[0]['sandbox']['sandboxID'])")
echo "copy reads: $("$A" exec "$K" cat /root/f)"
"$A" rm "$K"; "$A" rm "$SB"
echo "sparse conversion OK"
