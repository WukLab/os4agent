#!/bin/bash
# LibreOffice first-run dialogs with the new desk_osw.sh: open an .xlsx; check for the Tip of the Day DIALOG ("Tip of
# the Day: n/225"), the first-time bar; then edit a cell + Ctrl+S and check for the keep-format dialog.
cd /mnt/ssd2/vikranth/osworld
P="env PODMAN_TFORK_SKIP_SYSCTL=1 CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf CONTAINERS_CONF=$PWD/containers-os4agent.conf /mnt/ssd2/os4agent/podman-tfork.sh"
X=$(find cache -name "*.xlsx" -size +1k 2>/dev/null | head -1)
$P rm -f lo-test >/dev/null 2>&1
$P run -d --name lo-test --cgroupns=host --security-opt seccomp=unconfined --security-opt label=disable --shm-size=2g \
  --tmpfs /config:size=4g --tmpfs /tmp:size=1g --tmpfs /run:size=256m --entrypoint bash ghcr.io/wuklab/webtop:ubuntu-kde-osworld -c "$(cat desk_osw.sh)" >/dev/null
sleep 35
$P cp "$X" lo-test:/config/test.xlsx; $P exec lo-test chown abc:abc /config/test.xlsx
$P exec lo-test bash -c 'setsid nohup setpriv --reuid=abc --regid=abc --init-groups -- env HOME=/config DISPLAY=:1 QT_ACCESSIBILITY=1 soffice --calc /config/test.xlsx >/dev/null 2>&1 < /dev/null &'
sleep 25
ip=$($P inspect -f "{{.NetworkSettings.IPAddress}}" lo-test)
check() {
  curl -s -m 60 http://$ip:5000/accessibility > /tmp/vk_lo_tree.json
  python3 - <<'PY'
import json
t = json.load(open("/tmp/vk_lo_tree.json")).get("AT") or ""
print("Calc window:", "LibreOffice Calc" in t, "| Tip of the Day dialog:", "Tip of the Day:" in t,
      "| first-time bar:", "for the first time" in t, "| keep-format dialog:", "Use Excel 2007" in t or "Keep Current Format" in t)
PY
}
echo "after open:   $(check)"
$P exec lo-test bash -c "DISPLAY=:1 xdotool key Escape; sleep 1; DISPLAY=:1 xdotool type --delay 50 hello; DISPLAY=:1 xdotool key Return; sleep 1; DISPLAY=:1 xdotool key ctrl+s"
sleep 6
echo "after Ctrl+S: $(check)"
$P rm -f -t 0 lo-test >/dev/null; echo "lo-test left: $($P ps -a --filter name=^lo-test$ -q | wc -l)"
