#!/usr/bin/env bash
# AgentENV template `wa-shop142` from the docker image wa-shop-browser142 (shopping site + Chromium 142; the image the
# tfork and CRIU replays use), as agents/osworld_rl/SETUP.md §5 does for OSWorld: a local registry on the NVMe btrfs,
# push, then `aenv pull`, which converts the image, boots it with --start-cmd and snapshots it once --ready-cmd passes.
# Start command: the runtime dirs /docker-entrypoint.sh would make, then supervisord. Not the entrypoint itself: it
# re-initializes MySQL when /run/mysqld/.init is missing, and /run may be fresh in the VM.
# Ready: MySQL answers and Chromium's DevTools (127.0.0.1:9221) answers. 4 vCPU, 8 GiB (AENV's defaults).
#   bash agents/webarena_rl/setup/aenv/make_template.sh      (after start-server.sh)
set -euo pipefail
IMG=wa-shop-browser142:latest
REG=/mnt/data/ssd4/yutong/aenv_registry   # off the btrfs: the conversion needs ~263 GB there
A=$HOME/.local/bin/aenv
mkdir -p "$REG"
docker ps -a --format '{{.Names}}' | grep -qx aenv-registry || docker run -d --name aenv-registry \
    -p 127.0.0.1:5005:5000 -p 172.17.0.1:5005:5000 -v "$REG":/var/lib/registry registry:2
docker start aenv-registry >/dev/null
# the server reaches the registry over a shared docker network: here the host firewall (nftables input policy drop)
# blocks container -> host traffic, so OSWorld's 172.17.0.1:5005 is unreachable from aenv-server
docker network inspect aenv-net >/dev/null 2>&1 || docker network create aenv-net
for c in aenv-registry aenv-server; do docker network connect aenv-net $c 2>/dev/null || true; done
SRC=aenv-registry:5000
echo "$(date +%T) push $IMG"
docker tag "$IMG" 127.0.0.1:5005/$IMG
time docker push 127.0.0.1:5005/$IMG
# regctl is not on the server's PATH in this image (deps under /workspace/env/deps); lost if aenv-server is recreated
RC=$(docker exec aenv-server sh -c 'command -v regctl || ls /workspace/env/deps/regctl/*/regctl | tail -1')
docker exec aenv-server "$RC" registry set --tls disabled $SRC
# a build that was stopped (e.g. by disk_guard.sh) leaves its template holding the name: remove it unless ready
"$A" template ls | python3 -I -c "import json,sys; [print(t['templateID']) for t in json.load(sys.stdin)
    if 'wa-shop142' in (t.get('names') or []) and t['buildStatus'] != 'ready']" | while read -r t; do
    echo "removing unfinished template $t"; "$A" template delete "$t"; done
echo "$(date +%T) aenv pull"
START='sh -c "mkdir -p /run/nginx /var/tmp/nginx/client_body /run/mysqld && chown -R nginx:nginx /run/nginx /var/tmp/nginx && chown mysql:mysql /run/mysqld && exec supervisord -n -j /supervisord.pid"'
READY="mysql -u magentouser -pMyPassword magentodb -e 'select 1' >/dev/null 2>&1 && curl -sf http://127.0.0.1:9221/json/version >/dev/null"
time "$A" pull $SRC/$IMG --name wa-shop142 --cpu 4 --memory 8192 --start-cmd "$START" --ready-cmd "$READY" \
    --timeout 10800
"$A" template ls
echo "$(date +%T) done"
