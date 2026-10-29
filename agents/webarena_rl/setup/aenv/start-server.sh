#!/usr/bin/env bash
# AgentENV server in Docker for the WebArena runs (agents/osworld_rl/setup/aenv/start-server.sh with state on the NVMe
# btrfs and this folder's config.toml). Needs install.sh first. AENV needs io_uring: sets kernel.io_uring_disabled=0
# (runtime); tfork / CRIU runs need 2 again (setup/after_reboot.sh, or `sudo sysctl -w kernel.io_uring_disabled=2`).
# Server image: $AENV_SERVER_IMAGE, default upstream latest; the WebArena template needs build_server.sh's
# aenv-server:v0.2.4-uservsize256-sparse (user-image layers 256 GiB, sparse conversion layer). Joins docker network aenv-net (registry).
#   sudo AENV_SERVER_IMAGE=aenv-server:v0.2.4-uservsize256-sparse bash agents/webarena_rl/setup/aenv/start-server.sh
set -euo pipefail
cd "$(dirname "$0")"
STATE=/mnt/data/btrfs/aenv/env
IMAGE=${AENV_SERVER_IMAGE:-ghcr.io/kvcache-ai/aenv-server:latest}
[ -e /dev/ublk-control ] || { echo "ublk_drv not loaded: run install.sh" >&2; exit 1; }
sysctl -w kernel.io_uring_disabled=0
mkdir -p "$STATE"
docker rm -f aenv-server >/dev/null 2>&1 || true
docker run -d --name aenv-server --privileged --device /dev/kvm -v /dev:/dev \
  -v "$STATE":/workspace/env \
  -v "$PWD/config.toml:/workspace/config/default.toml:ro" \
  -p 127.0.0.1:8000:8000 "$IMAGE"
docker network inspect aenv-net >/dev/null 2>&1 && docker network connect aenv-net aenv-server
for _ in $(seq 120); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 2; done
curl -fs http://127.0.0.1:8000/health && echo
docker exec aenv-server cat /workspace/env/secrets/api-key > .api-key && chmod 600 .api-key
U=${SUDO_USER:-$USER}; UH=$(getent passwd "$U" | cut -d: -f6)
mkdir -p "$UH/.config/aenv"
printf "url = \"http://127.0.0.1:8000\"\napi_key = \"%s\"\n" "$(cat .api-key)" > "$UH/.config/aenv/credentials"
chown -R "$U" "$UH/.config/aenv" .api-key
docker inspect aenv-server --format 'image {{.Image}} created {{.Created}}'
