#!/usr/bin/env bash
# Idempotent. Run ON the env host (06) from this directory:  bash setup_webarena.sh   (no GPU; needs sudo for podman + browser deps)
set -e; HERE=$(cd "$(dirname "$0")" && pwd); source "$HERE/.env"
mkdir -p "$WA_ROOT"/{traces,cache}; cd "$WA_ROOT"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH=$HOME/.local/bin:$PATH
[ -d webarena-verified ] || git clone -q --depth 1 https://github.com/ServiceNow/webarena-verified
[ -d venv ] || UV_CACHE_DIR=$WA_ROOT/cache uv venv -p 3.11 venv
UV_CACHE_DIR=$WA_ROOT/cache uv pip install -q -p venv/bin/python -e ./webarena-verified "playwright>=1.55" openai
PLAYWRIGHT_BROWSERS_PATH=$WA_ROOT/cache/ms-playwright venv/bin/playwright install chromium >/dev/null
sudo $WA_ROOT/venv/bin/playwright install-deps chromium >/dev/null 2>&1 || echo "warn: playwright install-deps failed (chromium may miss system libs)"
# shared with the OSWorld pipeline: tracing proxy + host sampler (grpo_loop.py starts host_sampler.py from the env root)
cp "$HERE/../osworld_rl/proxy.py" "$HERE/proxy.py"; cp "$HERE/../osworld_rl/host_sampler.py" "$WA_ROOT/host_sampler.py"
${PODMAN:-sudo env CONTAINERS_STORAGE_CONF=/mnt/ssd2/podman/storage.conf podman} image exists docker.io/am1n3e/webarena-verified-shopping:latest || \
  ${PODMAN:-sudo env CONTAINERS_STORAGE_CONF=/mnt/ssd2/podman/storage.conf podman} pull -q docker.io/am1n3e/webarena-verified-shopping:latest
echo OK
