#!/bin/bash
# Build wa-shop-browser142 (image/Dockerfile.chr142: wa-shop-orig-browser + the Chromium 142 bundle) in docker, then copy
# it into the btrfs podman store tfork uses (setup/import_to_podman.py).
#   bash agents/webarena_rl/setup/build_image_chr142.sh        (from the os4agent checkout)
# Needs the bundle: bash agents/webarena_rl/setup/build_chromium_bundle.sh 3.22
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
TAR=/mnt/data/ssd4/yutong/tfork_build/chr_bundle/chr-142.0.7444.59.tar
CTX=/mnt/data/ssd4/yutong/tfork_build/image_chr142
mkdir -p "$CTX"
cp "$HERE/image/Dockerfile.chr142" "$HERE/image/chromium142.ini" "$CTX/"
cp "$TAR" "$CTX/"
echo "$(date +%T) docker build ..."
docker build -t wa-shop-browser142:latest -f "$CTX/Dockerfile.chr142" "$CTX"
rm -f "$CTX/$(basename "$TAR")"
echo "$(date +%T) import into podman (btrfs store) ..."
python3 "$HERE/setup/import_to_podman.py" wa-shop-browser142:latest
echo "$(date +%T) done"
