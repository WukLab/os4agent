#!/usr/bin/env bash
# AgentENV server image with a larger filesystem for user images: upstream v0.2.4 (the release of the aenv 0.2.4 CLI)
# + agentenv-v0.2.4-sparse-convert.patch: the conversion's RW layer is sparse (overlaybd-create -s); the default
#   log-structured one appends every block rewrite and grew past 142 GB for the ~111 GB WebArena image
# + agentenv-v0.2.4-user-vsize256.patch: converted user-image layers get a 256 GiB virtual size instead of
# LAYER_VIRTUAL_SIZE_GIB (64), which stays for AENV's own tools image (a compile-time-checked v1 contract,
# src/image/resolver.rs). AENV puts all layers of an image on one ext4 filesystem made at layer 0 with that size; the
# WebArena image's big layer is ~111 GB uncompressed, so with 64 GiB the conversion never finished (its scratch grew
# past 226 GB). Fresh clone in its own directory (the local ~/Repos/AgentENV checkout is older, from 2026-07-28, and
# has untracked work: left untouched); cargo capped at 8 jobs.
#   bash agents/webarena_rl/setup/aenv/build_server.sh      -> docker image aenv-server:v0.2.4-uservsize256-sparse
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TAG=v0.2.4
IMG=aenv-server:$TAG-uservsize256-sparse
D=/mnt/data/ssd4/yutong/aenv_build/AgentENV-$TAG
if [ ! -d "$D/.git" ]; then
    mkdir -p "$(dirname "$D")"
    git clone --depth 1 --branch $TAG https://github.com/kvcache-ai/AgentENV.git "$D"
fi
cd "$D"
git log -1 --format='%H %ci %s'
git checkout -- .
git apply "$HERE/agentenv-v0.2.4-user-vsize256.patch" "$HERE/agentenv-v0.2.4-sparse-convert.patch"
# cargo jobs <= 8 (host rule): every cargo step in the Dockerfile inherits this
sed -i 's|^ENV CARGO_TARGET_DIR=/build/target$|ENV CARGO_TARGET_DIR=/build/target\nENV CARGO_BUILD_JOBS=8|' \
    deploy/docker/Dockerfile.agentenv
git diff --stat
time DOCKER_BUILDKIT=1 docker build -f deploy/docker/Dockerfile.agentenv -t $IMG .
docker image ls aenv-server
