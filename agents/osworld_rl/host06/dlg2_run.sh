#!/bin/bash
cd /mnt/ssd2/vikranth/osworld
P="env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
B=https://huggingface.co/datasets/xlangai/ubuntu_osworld_file_cache/resolve/main
curl -sL -o /tmp/vk_w/italic.docx $B/libreoffice_writer/e246f6d8-78d7-44ac-b668-fcf47946cb50/Y22-2119-assign4.docx
curl -sL -o /tmp/vk_w/Invoices.xlsx $B/libreoffice_calc/1954cced-e748-45c4-9c26-9855b97fbc5e/Invoices.xlsx
for c in dw dc; do
  $P rm -f $c >/dev/null 2>&1
  $P run -d --name $c --cgroupns=host --security-opt seccomp=unconfined --security-opt label=disable --shm-size=2g \
    --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$(cat desk_osw.sh)" >/dev/null
  $P cp lo_gtk3/libvclplug_gtk3lo.so $c:/usr/lib/libreoffice/program/
done
sleep 30
$P exec dw mkdir -p /config/Desktop; $P cp /tmp/vk_w/italic.docx dw:/config/Desktop/italic.docx; $P exec dw chown -R abc:abc /config/Desktop
$P cp /tmp/vk_w/Invoices.xlsx dc:/config/Invoices.xlsx; $P exec dc chown abc:abc /config/Invoices.xlsx
iw=$($P inspect -f "{{.NetworkSettings.IPAddress}}" dw); ic=$($P inspect -f "{{.NetworkSettings.IPAddress}}" dc)
echo "$iw $ic" > /tmp/vk_dlg_ips
venv/bin/python dlg2.py $iw /home/user/Desktop/italic.docx '["key:ctrl+h", "sleep:3", "click:push-button:Format..."]' /tmp/vk_fmt > /tmp/vk_fmt.log 2>&1 &
venv/bin/python dlg2.py $ic /home/user/Invoices.xlsx '["key:ctrl+a", "click:push-button:Pivot Table", "sleep:3", "click:push-button:OK", "sleep:4"]' /tmp/vk_piv > /tmp/vk_piv.log 2>&1 &
wait; cat /tmp/vk_fmt.log /tmp/vk_piv.log
