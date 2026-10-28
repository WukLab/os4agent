#!/bin/bash
cd /mnt/ssd2/vikranth/nested_tests
sudo ./podman rm -f $(sudo ./podman ps -aq --filter name=wt-c) >/dev/null 2>&1
timeout 900 sudo env REPO_ROOT=/mnt/ssd2/os4agent PODMAN=$PWD/podman DEPTH=3 RUNG_SETTLE=${RUNG_SETTLE:-0} bash test/clone_live_recursive_webtop_chromium_chain.sh > logs/chromium_rerun.log 2>&1
echo "rc=$?" > logs/chromium_rerun.rc
l=$(grep -o '/mnt/btrfs/[^ "]*/crun-tfork.log' logs/chromium_rerun.log | head -1)
[ -n "$l" ] && sudo grep -h "Error" "$l" | sort | uniq -c > logs/chromium_rerun.errors
sudo ./podman rm -f $(sudo ./podman ps -aq --filter name=wt-c) >/dev/null 2>&1
