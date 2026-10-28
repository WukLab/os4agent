#!/usr/bin/env bash
# Idempotent. Run ON the env host (02: rootless podman, 06: system docker), from $WUK_ROOT:  bash setup_02.sh   (KVM, no GPU)
set -e; source "$(dirname "$0")/.env"
mkdir -p "$WUK_ROOT"/{traces,cache}; cd "$WUK_ROOT"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh; export PATH=$HOME/.local/bin:$PATH
[ -d OSWorld ] || git clone https://github.com/xlang-ai/OSWorld
[ -d venv ] || { UV_CACHE_DIR=$WUK_ROOT/cache uv venv -p 3.11 venv; UV_CACHE_DIR=$WUK_ROOT/cache uv pip install -p venv/bin/python -r OSWorld/requirements.txt openai; }
# upstream mismatch: lib_run_single calls agent.reset(..., vm_ip=...) but the UI-TARS agent's reset() lacks it
sed -i 's/def reset(self, runtime_logger=None):/def reset(self, runtime_logger=None, **kwargs):/' OSWorld/mm_agents/uitars15_v1.py
# runner hardcodes clipboard-paste typing (pyperclip), which has no backend in the VM -> every type action fails
sed -i 's/"input_swap": True/"input_swap": False/' OSWorld/scripts/python/run_multienv_uitars15_v1.py
# all envs start VMs under one file lock; upstream waits only 10 s, so with 16 envs most die at startup
sed -i 's/^LOCK_TIMEOUT = 10$/LOCK_TIMEOUT = 600/' OSWorld/desktop_env/providers/docker/provider.py
python3 "$(dirname "$0")/patch_storage.py" OSWorld   # VM_STORAGE_DIR: VM disks on a fast drive (06: root disk is an HDD)
# a11y tree per step + click->element hit (see a11y_hit.py)
cp "$(dirname "$0")/a11y_hit.py" OSWorld/ && python3 "$(dirname "$0")/patch_osworld.py" OSWorld
python3 "$(dirname "$0")/patch_grpo.py" OSWorld   # ROLLOUTS=G, ROLLOUT_TEMP
python3 "$(dirname "$0")/patch_a11y.py" OSWorld   # AGENT=a11y
python3 "$(dirname "$0")/patch_chrome_a11y.py" OSWorld   # web content in the a11y tree
cp "$(dirname "$0")/grpo_batch.json" OSWorld/evaluation_examples/
[ -c /dev/kvm ] && [ -w /dev/kvm ] || { echo "FAIL: /dev/kvm not writable"; exit 1; }
if ! command -v podman >/dev/null && docker info >/dev/null 2>&1; then docker pull happysixd/osworld-docker; : > docker.env; echo OK; exit 0; fi   # 06: system docker, nothing to configure
# user-owned podman storage (the default graphroot /mnt/btrfs/podman is root-owned)
mkdir -p $WUK_ROOT/podman $HOME/.config/containers
cat > $WUK_ROOT/storage.conf <<C
[storage]
driver = "overlay"
graphroot = "$WUK_ROOT/podman/graph"
runroot = "$XDG_RUNTIME_DIR/containers-osworld"
C
# 02's custom conmon is built without journald -> force file logging
cat > $WUK_ROOT/containers.conf <<C
[containers]
log_driver="k8s-file"
# OSWorld's provider only passes /dev/kvm; rootless needs tun + the kvm group kept inside the container
devices=["/dev/net/tun:/dev/net/tun:rwm","/dev/kvm:/dev/kvm:rwm"]
# host has nf_tables only (no ip_tables, no sudo) -> qemu user-mode net, forward the VM service ports explicitly
env=["NETWORK=user","USER_PORTS=5000,9222,8080"]
annotations=["run.oci.keep_original_groups=1"]
default_capabilities=["CHOWN","DAC_OVERRIDE","FOWNER","FSETID","KILL","NET_BIND_SERVICE","SETFCAP","SETGID","SETPCAP","SETUID","SYS_CHROOT","NET_ADMIN","NET_RAW"]
[engine]
events_logger="file"
C
export CONTAINERS_STORAGE_CONF=$WUK_ROOT/storage.conf CONTAINERS_CONF=$WUK_ROOT/containers.conf
mkdir -p ~/.config/systemd/user/podman.socket.d  # socket service must see the same storage
printf '[Service]\nEnvironment=CONTAINERS_STORAGE_CONF=%s\nEnvironment=CONTAINERS_CONF=%s\n' $WUK_ROOT/storage.conf $WUK_ROOT/containers.conf > ~/.config/systemd/user/podman.service.d.conf 2>/dev/null || true
mkdir -p ~/.config/systemd/user/podman.service.d; mv ~/.config/systemd/user/podman.service.d.conf ~/.config/systemd/user/podman.service.d/storage.conf
systemctl --user daemon-reload; systemctl --user restart podman.socket
# OSWorld's docker provider talks to the Docker API; podman serves it via a user socket.
systemctl --user enable --now podman.socket
export DOCKER_HOST=unix://$XDG_RUNTIME_DIR/podman/podman.sock
podman pull docker.io/happysixd/osworld-docker
printf "DOCKER_HOST=%s\nCONTAINERS_STORAGE_CONF=%s\nCONTAINERS_CONF=%s\n" $DOCKER_HOST $CONTAINERS_STORAGE_CONF $CONTAINERS_CONF | sed "s/^/export /" > docker.env; echo OK
