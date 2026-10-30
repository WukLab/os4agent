#!/bin/bash
cd /mnt/ssd2/vikranth/osworld
P="env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
start() {
  $P rm -f $1 >/dev/null 2>&1
  $P run -d --name $1 --cgroupns=host --security-opt seccomp=unconfined --security-opt label=disable --shm-size=2g \
    --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$(cat desk_osw.sh)" >/dev/null
  $P cp lo_gtk3/libvclplug_gtk3lo.so $1:/usr/lib/libreoffice/program/
}
start clk-w; start clk-c; sleep 30
curl -sL -o /tmp/vk_w/upper.docx https://huggingface.co/datasets/xlangai/ubuntu_osworld_file_cache/resolve/main/libreoffice_writer/d53ff5ee-3b1a-431e-b2be-30ed2673079b/presentation_instruction_2023_Feb.docx
for c in clk-w clk-c; do $P exec $c mkdir -p /config/Desktop; done
$P cp /tmp/vk_w/upper.docx clk-w:/config/Desktop/upper.docx; $P cp /tmp/vk_w/NetIncome.xlsx clk-c:/config/Desktop/NetIncome.xlsx
for c in clk-w clk-c; do $P exec $c chown -R abc:abc /config/Desktop; done
iw=$($P inspect -f "{{.NetworkSettings.IPAddress}}" clk-w); ic=$($P inspect -f "{{.NetworkSettings.IPAddress}}" clk-c)
echo skip-writer
echo "== Calc: click Add sheet"; venv/bin/python click_test.py clk-c $ic /home/user/Desktop/NetIncome.xlsx push-button Add "page-tab name" &
wait
$P rm -f -t 0 clk-w clk-c >/dev/null 2>&1
