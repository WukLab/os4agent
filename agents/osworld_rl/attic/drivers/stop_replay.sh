#!/bin/bash
# stop the replay driver + its runner, then remove any containers it started
for p in $(pgrep -f "^/bin/bash ./run_replay_all3.sh"); do sudo kill $p; done
for p in $(pgrep -f "osw_run.py --system [a-z]* --tasks /mnt/ssd2/vikranth/osworld/replay31.json"); do sudo kill $p; done
sleep 5
P="sudo env CONTAINERS_STORAGE_CONF=/mnt/btrfs/podman/storage.conf CONTAINERS_CONF=/mnt/ssd2/vikranth/osworld/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
$P ps -a --format "{{.Names}}" | xargs -r -n 20 $P rm -f >/dev/null 2>&1
echo "left: $(pgrep -fc 'osw_run.py') runner procs, $($P ps -aq | wc -l) containers"
