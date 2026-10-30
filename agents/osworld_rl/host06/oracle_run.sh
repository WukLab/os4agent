#!/bin/bash
# Oracle check of the 9 LibreOffice tasks on a desktop started like osw_run.py's start_source (GTK3 plugin copied in).
cd /mnt/ssd2/vikranth/osworld
P="env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
C=oracle-lo
$P rm -f $C >/dev/null 2>&1
$P run -d --name $C --cgroupns=host --security-opt seccomp=unconfined --security-opt label=disable --shm-size=2g \
  --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$(cat desk_osw.sh)" >/dev/null
echo "libreoffice-core: $($P exec $C dpkg-query -W -f='${Version}' libreoffice-core)"
$P cp lo_gtk3/libvclplug_gtk3lo.so $C:/usr/lib/libreoffice/program/
sleep 35
ip=$($P inspect -f "{{.NetworkSettings.IPAddress}}" $C)
echo "session SAL_USE_VCLPLUGIN: $($P exec $C bash -c 'tr "\0" "\n" < /proc/$(pgrep -f osworld_server -o || pgrep -f "main.py" -o)/environ | grep SAL_')"
cd OSWorld && ORACLE_C=$C ../venv/bin/python ../oracle_lo.py $ip swap 2>&1 | grep '^{'
