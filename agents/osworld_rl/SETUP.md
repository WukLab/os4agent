# Setting up a new env host

These steps rebuild what 06 runs. Paths are 06's. On another machine, use the flags or environment variables listed in
step 9 instead of editing code. Run everything as a sudo-capable user. The runner itself runs under `sudo`.

What 06 has, for reference: Ubuntu, kernel `7.0.0-34-generic` (the stock kernel, **not** os4agent's page-cache-CoW
kernel), 64 cores, 499 GB RAM, KVM, Docker, a btrfs disk at `/mnt/btrfs`, and os4agent WukLab `main` at `66406346a`.

## 1. Disk and sysctls

```bash
# Podman storage (tfork / CRIU rootfs, snapshots, tfork bundles) on a btrfs filesystem on NVMe: restores re-read the
# desktop's files from it, which saturated 06's SATA SSD. 06: /dev/nvme1n1p1 at /mnt/ssd3 (not in fstab; remount after
# a reboot). The Docker data-root and the AENV registry stay on /mnt/btrfs (06: /dev/sda1, SATA, in fstab with nofail).
sudo mkfs.btrfs -L nvme_btrfs /dev/<nvme partition>
sudo mkdir -p /mnt/ssd3 && sudo mount -o noatime,ssd,discard=async,space_cache=v2 /dev/<nvme partition> /mnt/ssd3
sudo mkdir -p /mnt/ssd3/podman /mnt/btrfs/registry
printf '[storage]\ndriver="btrfs"\ngraphroot="/mnt/ssd3/podman/storage"\nrunroot="/mnt/ssd3/podman/run"\n' \
  | sudo tee /mnt/ssd3/podman/storage.conf

# Required by tfork (os4agent README). io_uring is switched per run by osw_run.py.
sudo tee /etc/sysctl.d/90-tfork.conf <<'EOF'
kernel.io_uring_disabled = 2
fs.nr_open = 1048576
fs.inotify.max_user_instances = 524288
fs.inotify.max_user_watches = 1048576
kernel.apparmor_restrict_unprivileged_unconfined = 0
EOF
sudo sysctl --system
```

## 2. os4agent (tfork, crun, CRIU, conmon, podman)

tfork is os4agent's live-clone stack: a modified CRIU (`criu tfork` plus two kernel modules), crun with a `tfork` verb,
conmon with `--tfork`, and podman with `container clone --live`. Everything is built in-tree and used through the
wrapper `podman-tfork.sh`; no system podman files are replaced.

```bash
sudo apt install podman criu runc     # system podman supplies the rest of podman's components; criu/runc are for stock-criu
sudo git clone https://github.com/WukLab/os4agent /mnt/ssd2/os4agent && cd /mnt/ssd2/os4agent
sudo git checkout 66406346a && sudo git submodule update --init --recursive
sudo ./criu/build.sh       # libcriu + kernel modules (insmods them)
sudo ./crun/build.sh       # links against the in-tree libcriu
sudo ./conmon/build.sh     # --tfork flag
sudo ./podman/build.sh     # container clone --live
sudo patch -p1 < <this repo>/setup/podman-tfork-cgroup-path.patch     # needed for clone-of-clone (--base-fork)
```

Check the wiring (from os4agent's README):

```bash
cd /mnt/ssd2/os4agent
sudo env CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf ./podman-tfork.sh info \
  | grep -A2 -E "conmon:|ociRuntime:|cgroupManager:|graphRoot:|logDriver:"   # in-tree conmon/crun, cgroupfs, k8s-file, btrfs
lsmod | grep -E 'vma_cherrypick|criu_capbypass'                           # 06 had these two loaded
LD_LIBRARY_PATH=$PWD/criu/lib/c ./crun/crun --help | grep tfork
./conmon/bin/conmon --help 2>&1 | grep -- --tfork
sudo ./podman-tfork.sh container clone --help | grep -- --live
```

Notes:
- **The kernel modules don't persist.** After a reboot, load them again, for example by rerunning `criu/build.sh`.
- **No custom kernel was used.** os4agent also ships a page-cache-CoW kernel (`linux-pagecache-cow/`); 06's results
  were taken on the stock kernel, and `--tfork-overlay-btrfs` gives the shared page cache instead.
- **Sysctl preflight.** `podman-tfork.sh` checks the sysctls from step 1 on every call; set
  `PODMAN_TFORK_SKIP_SYSCTL=1` to skip that check.
- **`containers-os4agent.conf`** in this repo pins podman to `/mnt/ssd2/os4agent/{crun/crun,conmon/bin/conmon}`; edit it
  if os4agent lives elsewhere. A fixed config is required because the wrapper otherwise rewrites its own on every call,
  which races under parallel clones.
- **Optional end-to-end check:** `sudo bash setup/nested_tests/run_all.sh`. It expects the tests at
  `/mnt/ssd2/vikranth/nested_tests` and needs the image from step 3, so edit the paths in `run_all.sh` and `podman` first.

## 3. Desktop image `ghcr.io/wuklab/webtop:ubuntu-kde-osworld`

This image was only built locally and is not published. It is os4agent's KDE webtop (`ubuntu-img/` at `fb313e8dd`)
plus `setup/ubuntu-img-kde-osworld.patch`. The patch has four commits: the OSWorld control server on :5000, AT-SPI
accessibility, a google-chrome wrapper with socat, and LibreOffice without document recovery.

```bash
git clone https://github.com/WukLab/os4agent os4agent-img && cd os4agent-img && git checkout fb313e8dd
git am <this repo>/setup/ubuntu-img-kde-osworld.patch
sudo docker build --network host -t ghcr.io/wuklab/webtop:ubuntu-kde-osworld ubuntu-img
# copy it into the btrfs podman store that tfork / CRIU use
sudo env CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf /mnt/ssd2/os4agent/podman-tfork.sh \
  pull docker-daemon:ghcr.io/wuklab/webtop:ubuntu-kde-osworld
```

Podman containers on 06 have no DNS at build time, which is why the build uses `--network host`.

## 4. Container networking

Docker's FORWARD policy drops podman's bridge traffic, so containers have no internet and web tasks fail on tfork and
CRIU only. On 06 these rules were added by hand and **do not survive a reboot**:

```bash
sudo iptables -I DOCKER-USER -i podman0 -j ACCEPT
sudo iptables -I DOCKER-USER -o podman0 -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
```

## 5. AENV

```bash
echo '{"data-root": "/mnt/btrfs/docker"}' | sudo tee /etc/docker/daemon.json && sudo systemctl restart docker  # optional: space
curl -fsSL https://github.com/kvcache-ai/AgentENV/releases/latest/download/install-cli.sh | sh   # -> ~/.local/bin/aenv (06: 0.2.3)
sudo sysctl -w kernel.io_uring_disabled=0   # AENV needs io_uring; osw_run.py switches it back for tfork/CRIU runs
cd <this repo>/setup/aenv
sudo ./setup-host.sh          # ublk driver + sysctls (persistent)
sudo ./start-server.sh        # aenv-server in Docker with config.toml; state in /mnt/ssd2/aenv/env; writes CLI credentials
bash fork-smoke.sh            # a fork keeps in-memory state

# Template kde-osworld from the same image, through a local registry
sudo docker run -d --name aenv-registry -p 127.0.0.1:5005:5000 -p 172.17.0.1:5005:5000 \
  -v /mnt/btrfs/registry:/var/lib/registry registry:2
sudo docker tag ghcr.io/wuklab/webtop:ubuntu-kde-osworld 127.0.0.1:5005/webtop:ubuntu-kde-osworld
sudo docker push 127.0.0.1:5005/webtop:ubuntu-kde-osworld
sudo docker exec aenv-server regctl registry set --tls disabled 172.17.0.1:5005   # lost if the container is recreated
aenv pull 172.17.0.1:5005/webtop:ubuntu-kde-osworld --name kde-osworld          # builds and snapshots a VM
```

`start-server.sh` writes the CLI credentials (`~/.config/aenv/credentials`) and the API key to `setup/aenv/.api-key`,
which is git-ignored. The runner reads the key from `/mnt/ssd2/aenv/env/secrets/api-key`. The guest kernel's memory
reclaim (free-page reporting, DAMON) comes from `boot_args` in `config.toml`. Containers with no restart policy (both
here) need `docker start aenv-registry aenv-server` after a reboot.

## 6. This repo, OSWorld and the venv

```bash
git clone <this repo> /mnt/ssd2/vikranth/osworld && cd /mnt/ssd2/vikranth/osworld
git clone https://github.com/xlang-ai/OSWorld && git -C OSWorld checkout 1a572e62
python3 setup/patch_chrome_a11y.py OSWorld     # adds --force-renderer-accessibility to chrome launches in task configs
curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv -p 3.11 venv && uv pip install -p venv/bin/python -r setup/requirements-06.txt   # exact 06 versions
venv/bin/python a11y_owl_agent.py              # prints ok
```

The OSWorld runner patches in `attic/setup/` (UI-TARS, docker provider, `lib_run_single`) are **not** needed:
`osw_run.py` uses only `desktop_env` with its own provider. OSWorld downloads task files into `OSWorld/cache/` on
first use, so the host needs internet access.

## 7. Model server and trainer (RunPod)

The model runs on a RunPod A100 80GB. The env host only sends it requests through an ssh tunnel, and the GRPO trainer
runs on the same GPU.

**Create the pod** (from any machine; `RUNPOD_API_KEY` comes from runpod.io > Settings > API Keys):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/runpod_wa -N ''        # on the env host: the key osw_loop.py uses
export RUNPOD_API_KEY=...
scp 06:.ssh/runpod_wa.pub .                            # back on the laptop
setup/runpod.sh create osworld-model ~/.ssh/id_ed25519.pub runpod_wa.pub   # every key that needs ssh; prints the pod id
setup/runpod.sh info <pod-id>                          # prints `ssh -p <port> root@<ip>` once it is running
```

This creates a SECURE-cloud A100 80GB pod with the `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404` image, a 200 GB
container disk, no volume, and only port 22. `setup/runpod.sh stop|start <pod-id>` pauses and resumes it.

- **The ssh port changes on every start;** run `info` again after each one.
- **Nothing on the pod survives a restart.** Because the pod has no volume, a restarted pod comes back with an empty
  disk, so repeat the next step (the vLLM install and the model download take about 10 minutes).

**Serve the model** (on the pod):

```bash
scp -P <port> pod_serve.sh train_grpo.py root@<ip>:/root/        # then on the pod:
mkdir -p /root/osworld_rl && mv /root/train_grpo.py /root/osworld_rl/
bash /root/pod_serve.sh                       # rollouts / recordings only
GPU_UTIL=0.4 bash /root/pod_serve.sh          # GRPO loop: leaves GPU memory for train_grpo.py
```

`pod_serve.sh` installs vLLM 0.11.0 + transformers 4.57.1 (`transformers>=5` breaks vLLM 0.11 on Qwen3-VL), downloads
Qwen3-VL-8B-Instruct into `/root/hf` and serves it as `qwen3vl8b` on :8000. The server runs text-only
(`--limit-mm-per-prompt` image/video 0) with LoRA hot-loading on (rank 16). It writes `/root/serve.status` once it
answers. The log is `/root/vllm.log`.

**Connect from the env host:**

```bash
ssh -i ~/.ssh/runpod_wa -f -N -L 8100:localhost:8000 -p <port> root@<ip>
curl -s localhost:8100/v1/models          # lists qwen3vl8b
```

Live runs point at it with `DOUBAO_API_URL=http://127.0.0.1:8100/v1`. Port 8100, because 8000 on 06 is aenv-server.
`osw_loop.py --pod root@<ip> --pod-port <port>` opens the same tunnel itself, rsyncs rollouts to `/root/data/` and trains
into `/root/adapters/`. Stop the pod when you're done, because RunPod bills while it runs.

## 8. Smoke tests

```bash
R=traces/smoke
sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 venv/bin/python osw_run.py --system tfork --limit 1 --rollouts 2 --result-dir $R
for s in criu aenv; do
  sudo env DOUBAO_API_URL=http://127.0.0.1:1/v1 venv/bin/python osw_run.py --system $s --limit 1 --rollouts 2 \
    --replay $R --result-dir ${R}_$s
done
python3 analyze.py progress traces/smoke*     # expect: groups done 1, errors 0
```

The first run calls the model and makes a recording; the other two replay it, so they need no model. Replay a
recording from 06 (`traces/rec32v2_tfork`) to compare against the published numbers.

## 9. Host-specific settings

| what | default (06) | override |
|---|---|---|
| os4agent checkout | `/mnt/ssd2/os4agent` | `osw_run.py --os4agent`, `compare.sh` env `OS4AGENT` |
| podman storage.conf | `/mnt/ssd3/podman/storage.conf` | `--storage-conf`, env `STORAGE_CONF` |
| AENV API key | `/mnt/ssd2/aenv/env/secrets/api-key` | `--aenv-key`, env `AENV_KEY` |
| aenv CLI / its HOME | `~$SUDO_USER/.local/bin/aenv` | `--aenv-cli`, `--aenv-home` |
| crun / conmon binaries | `/mnt/ssd2/os4agent/...` | edit `containers-os4agent.conf` |
| pod ssh key | `~/.ssh/runpod_wa` | `osw_loop.py --pod-key` |

## Housekeeping

- A clone that is killed, or runs with `PODMAN_TFORK_NO_REAP=1`, leaves its bundle (mounts plus a btrfs snapshot)
  under `tfork-bundles/`. With no containers running, `sudo bash setup/clean_tfork_bundles.sh` removes them.
- Never `pkill -f` a pattern that also appears in your own ssh command line. Run long jobs as
  `setsid nohup bash script.sh &`.
