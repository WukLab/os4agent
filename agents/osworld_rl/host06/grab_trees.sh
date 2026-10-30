#!/bin/bash
# save the live accessibility XML of the shot6v2 rollouts for one task: grab_trees.sh <task8> <name>
cd /mnt/ssd2/vikranth/osworld
P="sudo env CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
g=$(python3 -c "import json; print(next(e['g'] for e in map(json.loads, open('traces/shot6v2_shot/events.jsonl')) if e['event'] == 'fork' and e['task'].startswith('$1')))")
mkdir -p /tmp/vk_trees
for n in $($P ps --format "{{.Names}}" | grep -E "^osw-shot6v2-shot-t$g-k-[0-9]+$"); do
  ip=$($P inspect -f "{{.NetworkSettings.IPAddress}}" $n)
  curl -s -m 60 http://$ip:5000/accessibility | python3 -c "import json,sys; d=json.load(sys.stdin); open('/tmp/vk_trees/$2_${n##*-}.xml','w').write(d.get('AT') or '')" && echo "$n -> /tmp/vk_trees/$2_${n##*-}.xml $(wc -c < /tmp/vk_trees/$2_${n##*-}.xml) bytes"
done
