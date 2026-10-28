#!/bin/bash
# Ported nested-fork tests against WukLab main (/mnt/ssd2/os4agent). podman-tfork.sh fills the empty per-copy cgroup-path itself.
cd /mnt/ssd2/vikranth/nested_tests; mkdir -p logs; rm -rf logs/*
clean() {
    sudo ./podman rm -f $(sudo ./podman ps -aq --filter name=tfork- --filter name=webtop --filter name=wt-c) >/dev/null 2>&1
    sudo rm -rf /tmp/ubuntu_webtop_recursive /tmp/webtop-chromium-chain /tmp/tfork-fanout /tmp/tfork-chain-stress*
}
for W in ${PASSES:-podman}; do
    E="REPO_ROOT=/mnt/ssd2/os4agent PODMAN=/mnt/ssd2/vikranth/nested_tests/$W"
    run() { local name=$W.$1; shift; clean; timeout 1800 sudo env $E "$@" > logs/$name.log 2>&1; echo "$name rc=$?" >> logs/summary.txt; }
    run recursive_clone      CLONE_EXTRA=--tfork-overlay-btrfs bash test/clone_live_recursive_clone_test.sh
    run fanout_cgns_private  CGROUPNS=private bash test/clone_live_recursive_fanout_test.sh
    run fanout_cgns_host     CGROUPNS=host    bash test/clone_live_recursive_fanout_test.sh
    run fanout1_cgns_host    CGROUPNS=host COPIES=1 bash test/clone_live_recursive_fanout_test.sh
    run recursive_webtop     bash test/clone_live_recursive_webtop_test.sh
    run webtop_chromium_d5   DEPTH=5 RUNG_SETTLE=30 bash test/clone_live_recursive_webtop_chromium_chain.sh
    run chain_stress_d10     DEPTH=10 CLONE_EXTRA=--tfork-overlay-btrfs bash test/clone_live_recursive_chain_stress.sh
done
clean; touch logs/ALL.done
