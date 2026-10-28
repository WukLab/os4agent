#!/usr/bin/env bash
# Root-only host prep for AENV (subset of upstream scripts/docker-setup.sh).
# Skips its fs.inotify.max_user_instances=8192: tfork/webtop need 524288.
set -euo pipefail
echo "options ublk_drv ublks_max=4096" > /etc/modprobe.d/aenv-ublk.conf
echo ublk_drv > /etc/modules-load.d/aenv-ublk.conf
modprobe ublk_drv ublks_max=4096
modprobe nf_conntrack
cat > /etc/sysctl.d/99-aenv.conf <<SYS
net.ipv4.neigh.default.gc_thresh1 = 4096
net.ipv4.neigh.default.gc_thresh2 = 8192
net.ipv4.neigh.default.gc_thresh3 = 16384
net.netfilter.nf_conntrack_max = 1048576
kernel.pid_max = 4194304
SYS
sysctl -p /etc/sysctl.d/99-aenv.conf
ls -l /dev/ublk-control
