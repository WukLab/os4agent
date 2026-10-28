#!/usr/bin/env bash
# Start AENV server in Docker; state on the big disk. Needs setup-host.sh first.
set -euo pipefail
cd "$(dirname "$0")"
[ -e /dev/ublk-control ] || { echo "ublk_drv not loaded: run sudo ./setup-host.sh" >&2; exit 1; }
mkdir -p /mnt/ssd2/aenv/env
docker rm -f aenv-server >/dev/null 2>&1 || true
docker run -d --name aenv-server --privileged --device /dev/kvm -v /dev:/dev \
  -v /mnt/ssd2/aenv/env:/workspace/env \
  -v "$PWD/config.toml:/workspace/config/default.toml:ro" \
  -p 127.0.0.1:8000:8000 ghcr.io/kvcache-ai/aenv-server:latest
for _ in $(seq 60); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 1; done
curl -fs http://127.0.0.1:8000/health && echo
docker exec aenv-server cat /workspace/env/secrets/api-key > .api-key && chmod 600 .api-key
mkdir -p ~/.config/aenv && printf "url = \"http://127.0.0.1:8000\"\napi_key = \"%s\"\n" "$(cat .api-key)" > ~/.config/aenv/credentials
