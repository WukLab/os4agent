#!/usr/bin/env bash
# Memory CoW comparison: os4agent TFORK vs stock CRIU vs AENV on the OSWorld desktop.
# Usage: sudo ./run.sh [N=4] [SYSTEMS=tfork,criu,aenv]
set -euo pipefail
cd "$(dirname "$0")"
N="${1:-4}"; SYSTEMS="${2:-tfork,criu,aenv}"
REPO=$(cd ../.. && pwd)
mkdir -p /mnt/ssd2/podman/{storage,run}
printf "[storage]\ndriver=\"overlay\"\ngraphroot=\"/mnt/ssd2/podman/storage\"\nrunroot=\"/mnt/ssd2/podman/run\"\n" > /mnt/ssd2/podman/storage.conf
export CONTAINERS_STORAGE_CONF=/mnt/ssd2/podman/storage.conf
IMG=ghcr.io/wuklab/webtop:ubuntu-kde
if [[ "$SYSTEMS" == *tfork* || "$SYSTEMS" == *criu* ]]; then
  "$REPO/podman-tfork.sh" image exists $IMG || "$REPO/podman-tfork.sh" pull $IMG
fi
if [[ "$SYSTEMS" == *aenv* ]]; then
  ../aenv/setup-host.sh
  curl -fs http://127.0.0.1:8000/health >/dev/null 2>&1 || ../aenv/start-server.sh
mkdir -p ~/.config/aenv && printf "url = \"http://127.0.0.1:8000\"\napi_key = \"%s\"\n" "$(cat /mnt/ssd2/aenv/env/secrets/api-key)" > ~/.config/aenv/credentials
fi
python3 memcompare.py --systems "$SYSTEMS" --n "$N"
