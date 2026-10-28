#!/bin/bash
# Where does a forked AENV VM's private memory come from? Measure the copy's VMM (host side) after guest actions.
set -u; A="$HOME/.local/bin/aenv"; KEY=$(sudo cat /mnt/ssd2/aenv/env/secrets/api-key)
echo 0 | sudo tee /proc/sys/kernel/io_uring_disabled >/dev/null
sudo docker start aenv-server >/dev/null; for i in $(seq 90); do curl -fs http://127.0.0.1:8000/health >/dev/null && break; sleep 2; done
vmms() { for p in $(pgrep -x firecracker); do sudo ls -l /proc/$p/fd 2>/dev/null | grep -q ublkb && echo $p; done | sort; }
mem() {  # <label> <vmm pid>: host-side PSS/anon/file of the copy's VMM
  sudo awk -v l="$1" '/^Rss:/{r=$2} /^Pss_Anon:/{an=$2} /^Pss_File:/{f=$2} /^Pss:/{p=$2} END{printf "%-34s rss %6.0f MiB  pss %6.0f  anon %6.0f  file %6.0f\n", l, r/1024, p/1024, an/1024, f/1024}' /proc/$2/smaps_rollup; }
gx() { $A exec $1 -- bash -c "$2" 2>&1 | tail -3; }
b0=$(vmms); SRC=$($A start kde-osworld --detach --timeout 1800 | awk '{print $NF}' | tail -1); sleep 3
echo "== guest: $(gx $SRC 'uname -r; ls /sys/bus/virtio/drivers/ 2>/dev/null | tr "\n" " "; echo; grep -o "damon[^ ]*" /proc/cmdline | tr "\n" " "; echo; free -m | sed -n 2p')"
gx $SRC 'dd if=/dev/urandom of=/var/tmp/big bs=1M count=1024 status=none; sync; echo 3 > /proc/sys/vm/drop_caches; echo prepared'
b1=$(vmms)
K=$(curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{"count": 1, "timeout": 1800}' http://127.0.0.1:8000/sandboxes/$SRC/fork | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['sandbox']['sandboxID'])")
sleep 3; V=$(comm -13 <(echo "$b1") <(vmms) | head -1); echo "copy $K vmm $V"
mem "copy right after fork" $V; sleep 60; mem "copy after 60 s idle" $V
gx $K 'cat /var/tmp/big > /dev/null; free -m | sed -n 2p'; sleep 2; mem "after reading 1 GiB file in guest" $V
gx $K 'echo 3 > /proc/sys/vm/drop_caches; free -m | sed -n 2p'; sleep 30; mem "after guest drop_caches + 30 s" $V
gx $K 'python3 -c "b=bytearray(1<<30); b[::4096]=b\"x\"*(len(b)//4096); print(\"alloc\")"; free -m | sed -n 2p'; sleep 30; mem "after alloc+free 1 GiB + 30 s" $V
gx $K 'cat /sys/kernel/mm/damon/admin/kdamonds/nr_kdamonds 2>/dev/null; grep -i "page_report\|balloon" /proc/vmstat 2>/dev/null | head -3; dmesg 2>/dev/null | grep -i -m2 "balloon\|damon"'
for s in $K $SRC; do curl -s -X DELETE -H "X-API-Key: $KEY" http://127.0.0.1:8000/sandboxes/$s -o /dev/null; done
sudo docker stop aenv-server >/dev/null; echo 2 | sudo tee /proc/sys/kernel/io_uring_disabled >/dev/null
