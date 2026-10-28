#!/usr/bin/env bash
# Step 1 test, run from laptop or RunPod: can we reach 02 and does it have what OSWorld needs?
source "$(dirname "$0")/.env"; ssh -p $WUK_PORT $WUK_USER@$WUK_HOST 'hostname; ls -l /dev/kvm; podman --version; df -h '"$WUK_ROOT"' | tail -1; podman info 2>&1 | grep -m1 graphRoot'
