#!/usr/bin/env bash
# AENV fork smoke test: in-memory counter must survive the fork (same check as the tfork test).
set -euxo pipefail
cd "$(dirname "$0")"
A=${AENV:-$(eval echo ~${SUDO_USER:-$USER})/.local/bin/aenv}; KEY=$(cat .api-key); URL=http://127.0.0.1:8000
$A template ls | grep -q alpine || $A pull docker.io/library/alpine:3.20 --name alpine
SB=$($A start alpine --detach | grep -oE "[A-Za-z0-9_-]{8,}" | tail -1)
$A exec "$SB" sh -c "nohup sh -c \"i=0; while true; do i=\\\$((i+1)); echo \\\$i > /tmp/count; sleep 0.5; done\" >/dev/null 2>&1 &"
sleep 5; echo "source count: $($A exec "$SB" cat /tmp/count)"
time curl -fsS -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d "{\"count\": 2, \"timeout\": 600}" "$URL/sandboxes/$SB/fork" | tee fork.json
sleep 2
for c in $(python3 -c "import json;[print(e[\"sandbox\"][\"sandboxID\"]) for e in json.load(open(\"fork.json\")) if \"sandbox\" in e]"); do
  a=$($A exec "$c" cat /tmp/count); sleep 2; b=$($A exec "$c" cat /tmp/count)
  echo "child $c count: $a -> $b (counter process alive in child iff b > a)"
  $A rm "$c"
done
$A rm "$SB"
