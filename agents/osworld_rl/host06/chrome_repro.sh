#!/bin/bash
# Reproduce the parasite SIGSEGV in a tfork-restored Chromium renderer with CRIU debug logs.
# One Chrome desktop (as task 9f935cce starts it) -> G (8 copies, persistent) -> 8 parallel chains, each forking its
# newest copy GEN times (keep copy 0, rm copy 1, stop the previous desktop: a run of speculation hits). Every clone at
# CRIU_TFORK_LOG_LEVEL=4; a failed clone's bundle is kept and its logs copied to $OUT.
cd /mnt/ssd2/vikranth/osworld
GEN=${GEN:-10}; OUT=traces/chrome_repro; mkdir -p $OUT; rm -f $OUT/*.txt
export PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf CRIU_TFORK_LOG_LEVEL=4
P=/mnt/ssd2/os4agent/podman-tfork.sh
F="--tfork-tcp-close --tfork-ghost-limit=67108864 --tfork-overlay-btrfs"
$P ps -a --format "{{.Names}}" | grep "^cr-" | xargs -r $P rm -f -t 0 >/dev/null 2>&1
$P run -d --name cr-src --cgroupns=host --ulimit nofile=1048576:1048576 --security-opt seccomp=unconfined --security-opt label=disable \
  --shm-size=2g --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$(cat desk_osw.sh)" >/dev/null
sleep 40
$P exec cr-src bash -c 'setsid nohup setpriv --reuid=abc --regid=abc --init-groups -- env HOME=/config DISPLAY=:1 XDG_RUNTIME_DIR=/config/.XDG google-chrome --force-renderer-accessibility --remote-debugging-port=1337 --no-first-run https://www.justice.gov/ >/tmp/chrome.log 2>&1 < /dev/null &'
sleep 30
echo "renderers in source: $($P exec cr-src pgrep -fc -- --type=renderer)"
G=($($P container clone --live --copies=8 --persistent=async $F --name cr-g cr-src 2>/dev/null | grep -E "^[0-9a-f]{64}$"))
echo "group copies: ${#G[@]}"
sleep 20  # fresh copies: netlink "socket has data to read" if forked at once (osw_run settles too)
chain() {  # $1 = chain index, $2 = first desktop
  local cur=$2 prev="" n out ids
  for n in $(seq 1 $GEN); do
    $P exec $cur true >/dev/null 2>&1; sleep 0.1
    for try in 1 2 3; do  # osw_run retries the same netlink error
      out=$(PODMAN_TFORK_NO_REAP=1 $P container clone --live --copies=2 $F --name cr-c$1x$n$try $cur 2>&1)
      ids=($(echo "$out" | grep -E "^[0-9a-f]{64}$"))
      [ ${#ids[@]} = 2 ] && break
      echo "$out" | grep -q "socket has data to read" || break
      echo "chain $1 gen $n: netlink, retry"; sleep 3
    done
    if [ ${#ids[@]} != 2 ]; then
      b=$(echo "$out" | grep -o "/[^ \"]*/tfork-bundles/[0-9a-f]*" | head -1)
      echo "chain $1 gen $n: FAILED $(echo "$out" | grep -o 'Error.*' | tail -1 | cut -c1-150)"
      { echo "$out"; [ -n "$b" ] && for f in $b/crun-tfork.log $b/img/*.log; do echo "===== $f"; cat $f 2>/dev/null; done; } > $OUT/chain$1_gen$n.txt
      return
    fi
    $P rm -f -t 0 ${ids[1]} >/dev/null 2>&1
    [ -n "$prev" ] && $P stop -t 0 $cur >/dev/null 2>&1
    prev=$cur; cur=${ids[0]}
    sleep 3
  done
  echo "chain $1: $GEN generations ok"
}
for i in $(seq 0 $((${#G[@]} - 1))); do chain $i ${G[$i]} & done; wait
echo "debug log size of one good clone: $(ls -la /mnt/ssd3/podman/storage/tfork-bundles/*/img/tfork.log 2>/dev/null | head -1 | awk '{print $5}') bytes"
$P ps -a --format "{{.Names}}" | grep -E "^cr-" > /tmp/vk_cr_names.txt
echo "cr- containers to remove: $(wc -l < /tmp/vk_cr_names.txt)"
