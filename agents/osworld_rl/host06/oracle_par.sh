#!/bin/bash
# Oracle check of the 9 LibreOffice tasks, 3 desktops in parallel, each started like osw_run.py's start_source.
cd /mnt/ssd2/vikranth/osworld
P="env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
one() {  # $1 container, rest: task id prefixes
  C=$1; shift
  $P rm -f $C >/dev/null 2>&1
  $P run -d --name $C --cgroupns=host --security-opt seccomp=unconfined --security-opt label=disable --shm-size=2g \
    --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$(cat desk_osw.sh)" >/dev/null
  $P cp lo_gtk3/libvclplug_gtk3lo.so $C:/usr/lib/libreoffice/program/
  sleep 35
  ip=$($P inspect -f "{{.NetworkSettings.IPAddress}}" $C)
  (cd OSWorld && ORACLE_C=$C ../venv/bin/python ../oracle_lo.py $ip swap "$@" 2>&1 | grep '^{')
  $P rm -f -t 0 $C >/dev/null 2>&1
}
one oracle-lo-a 42e0a640 357ef137 26a8440e > /tmp/vk_or_a.out &
one oracle-lo-b 7a4e4bc8 6e99a1ad 4e6fcf72 > /tmp/vk_or_b.out &
one oracle-lo-c 0810415c 7dbc52a6 5d901039 > /tmp/vk_or_c.out &
wait
cat /tmp/vk_or_[abc].out
