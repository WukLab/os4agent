# OSWorld GRPO on forked desktops

GRPO needs several rollouts of the same task from the same starting state. Instead of resetting a desktop for each
one, we set the task up once and fork the desktop. This repo runs OSWorld rollouts that way, with Qwen3-VL-8B
driving the desktop through its accessibility tree (text only, no screenshots), and measures how much memory each
forking mechanism costs.

Four systems are supported:

- `tfork`: os4agent's live clone. One `podman container clone --live --copies=N` makes all copies, which share
  memory copy-on-write with the source.
- `criu`: the baseline. N serial single-copy clones through our CRIU, each a full dump and restore with
  `--tfork-full-memcopy`, so nothing is shared.
- `stock-criu`: runc and the distro's CRIU. One `podman container checkpoint --leave-running`, then N restores.
- `aenv`: the fork API of [AgentENV](https://github.com/kvcache-ai/AgentENV), which runs each desktop in a
  Firecracker microVM.

Each task group goes through the same steps on every system: start a source desktop, run the OSWorld task setup,
fork it into N copies, run the N rollouts in parallel, then score each one with OSWorld's checker. A sampler records
memory for every live environment every 2 s. Task batches leave out Thunderbird, VS Code and OS tasks.

## Results

32 task groups of 8 rollouts each, replaying `traces/rec32v2_tfork` with `--parallel 8`:

| | tfork (overlay) | CRIU | AENV |
|---|---|---|---|
| PSS per group right after the fork (GiB) | 1.31 | 5.42 | 2.57 |
| PSS per group after the rollouts (GiB) | 2.95 | 7.06 | 6.58 |
| Peak PSS over the run (GiB) | 32.8 | 64.5 | 66.0 |
| Run time (min) | 29 | 37 | 47 |

Three things shaped these numbers.

tfork has to run with `--overlay-rootfs 1`, which is the default. Without it every copy gets its own btrfs snapshot
and therefore its own page cache, so 8 restoring copies all re-read every binary from the SATA SSD at once. The restore
then overruns tfork's hard-coded 10 s wait (`tfork_restore_wait_timeout_ms`, `criu/cr-restore.c:238`) and the clone
fails with `tfork restore wait timed out after 10000ms`. With 4 concurrent 8-copy clones, 0 of 4 succeeded without
overlay and 43 of 44 with it. The runner retries a failed clone up to 5 times (backing off 20, 40, 60, 80 s), but the
real fix belongs upstream: make that timeout configurable.

The runner talks to AENV VMs directly. AENV's HTTP proxy cuts off any request after 30 s, and under load the
LibreOffice accessibility tree takes longer than that. So `osw_run.py` relays each VM port from inside
`aenv-server`'s network namespace straight to the VM's slot address (`Forwarder`). It matches each forked sandbox to
its Firecracker process by writing a tag through `aenv exec` and reading it back over the direct path.

An AENV fork shares memory at first, but whatever the guest reads afterwards lands in its own page cache, which is
private host memory charged to that VM. That is why an AENV copy grows by about 0.5 GiB over a rollout, against
about 0.18 GiB for tfork.

## Running

Everything runs on the env host (06) from `/mnt/ssd2/vikranth/osworld`, which holds this repo plus `OSWorld/`,
`venv/` and `traces/`. The model is served from a RunPod A100, reached through an ssh tunnel on port 8100. To set
up a new machine, follow [SETUP.md](SETUP.md).

A live run calls the model. This is how the recording that the comparison replays was made:

```bash
sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 venv/bin/python osw_run.py \
    --system tfork --tasks grpo_batch32v2.json --parallel 8 --result-dir traces/rec32v2_tfork
```

The memory comparison replays that recording on each system in turn, so it doesn't need the model:

```bash
./compare.sh traces/rec32v2_tfork grpo_batch32v2.json traces/replay32 tfork criu aenv -- --parallel 8
python3 analyze.py progress traces/replay32_*
python3 analyze.py memory tfork=traces/replay32_tfork criu=traces/replay32_criu aenv=traces/replay32_aenv
python3 analyze.py clones traces/replay32_tfork
```

The GRPO loop runs rollouts on 06 and training on the pod, and opens the tunnel itself:

```bash
nohup venv/bin/python osw_loop.py --exp osw_tfork --system tfork --epochs 4 \
    --pod root@<pod-ip> --pod-port <port> > traces/osw_tfork_loop.log 2>&1 &
```

`python3 make_osw_batch.py > grpo_batch64.json` builds a 64-task batch: the 32 tasks of `grpo_batch32v2.json` plus
32 more, seed 0.

Start long jobs detached (`setsid nohup bash script.sh &`) so they survive a dropped ssh session.

### Options

| flag | default | |
|---|---|---|
| `--system` | required | `tfork`, `criu`, `stock-criu` or `aenv` |
| `--tasks`, `--limit` | `grpo_batch32v2.json`, all | task batch; `--limit N` runs only the first N |
| `--rollouts`, `--max-steps` | 8, 15 | copies per group, agent steps per rollout |
| `--parallel` | 1 | task groups alive at once (0 means all) |
| `--fork-concurrency` | 4 | task groups forking at once |
| `--base-fork` | 0 | boot one desktop and fork it into every task's source, making a two-level tree |
| `--replay DIR`, `--replay-latency` | off, 1.0 | replay a recorded run, sleeping this multiple of the recorded model latency per step |
| `--model`, `--temperature` | `qwen3vl8b`, 1.0 | served model name for live runs |
| `--spec tage`, `--spec-topk` | off, 8 | shadow action predictor; its guesses are never executed |
| `--overlay-rootfs` | 1 | tfork: pass `--tfork-overlay-btrfs` so copies share one rootfs page cache |
| `--full-memcopy` | 1 | criu: pass `--tfork-full-memcopy`, so nothing is shared with the source |
| `--save-ckpt DIR` | off | criu: keep each group's CRIU image |
| `--net`, `--seccomp` | auto | slirp and `seccomp_nopkey.json` for stock-criu, bridge and unconfined otherwise |
| `--image` | `ghcr.io/wuklab/webtop:ubuntu-kde-osworld` | desktop image for the podman systems |
| `--aenv-template` | `kde-osworld` | AENV template built from the same image |
| `--sample-s` | 2.0 | memory sampling interval |

The runner prepares the host for the chosen system. AENV needs io_uring enabled and `aenv-server` running, while
tfork and CRIU need io_uring disabled (`kernel.io_uring_disabled=2`) and `aenv-server` stopped. `compare.sh` leaves
io_uring disabled when it finishes.

### Output

A result directory contains:

- `config.json`, the arguments of the run;
- `events.jsonl`, with boot, setup, fork, rollout and group events, the memory events carrying a full snapshot;
- `mem.jsonl`, the sampler's output;
- `failed_clones/`, the CRIU logs of any clone that failed;
- one `<domain>/<task>__g<k>/` per rollout, holding `chat.jsonl` (the model's inputs and outputs, used for replay and
  training), `traj.jsonl`, `result.txt`, `timing.json` and a `step_<n>.png` per step.

## How memory is measured

The sampler (`Mem` in `osw_run.py`) writes a line to `mem.jsonl` every `--sample-s` seconds. The same snapshot is
attached to the `mem_before_fork`, `fork` and `group_done` events. For each environment it records:

- on the podman systems, PSS (split into anon, file and shmem) and RSS summed over `/proc/<pid>/smaps_rollup` of
  every process in the container's pid namespace. It also records the container cgroup's `memory.current` and
  `memory.stat` (anon, file, shmem, kernel), which also count tmpfs and unmapped page cache that PSS misses;
- on AENV, the PSS of the Firecracker process, which holds the guest's RAM.

For the host it records `MemTotal - MemAvailable` relative to the start of the run (`used_delta_mib`), along with
AnonPages, Shmem and Cached. It also logs CPU user, sys and iowait, the load average, and the phase each live group
is in (boot, setup, fork, rollouts, teardown).

PSS splits each shared page among the processes that map it, so per-group sums add up without double counting.
`analyze.py memory` turns this into the per-group table and the run peaks above.

## How the forks are done

tfork makes all copies in one call:

```
podman container clone --live --copies=8 --persistent=async --tfork-tcp-close \
    --tfork-ghost-limit=67108864 --tfork-overlay-btrfs --name <src>-k <src>
```

The CRIU baseline (CKPT mode) makes one copy per call:

```
podman container clone --live --copies=1 --persistent=sync --tfork-tcp-close \
    --tfork-ghost-limit=67108864 --tfork-full-memcopy --name <src>-k<i> <src>
```

Source containers run with `--cgroupns=host`, since restores otherwise fail in cgroupd. They also run with
`--ulimit nofile=1048576:1048576`, because Chromium's in-flight SCM_RIGHTS file descriptors otherwise hit
ETOOMANYREFS. Just before a freeze the runner does a `podman exec <src> true`, so tini reaps any exec children first.
After every fork, on every system, it refills the copies' empty `/etc/hosts` and restarts a Chrome task's socat
relay for the DevTools port, both of which the fork loses.

Every podman call goes through `/mnt/ssd2/os4agent/podman-tfork.sh` with
`CONTAINERS_STORAGE_CONF=/mnt/ssd3/podman/storage.conf` (btrfs on NVMe) and `CONTAINERS_CONF=containers-os4agent.conf`. The fixed
config matters: otherwise the wrapper rewrites its own containers.conf on every call, and parallel clones race on it.

## Changes to os4agent

tfork, crun and CRIU are unmodified WukLab main. The one change is to the wrapper `/mnt/ssd2/os4agent/podman-tfork.sh`
on 06. It is uncommitted there; the diff is `setup/podman-tfork-cgroup-path.patch` and the original is saved at
`/mnt/ssd2/vikranth/podman-tfork.sh.bak`.

The patch adds `tfork_fix_cgroup_path`, which runs before every `clone --live` and fills in the source's empty
`"cgroup-path"` in `/run/crun/<id>/status`. Without it, cloning a clone fails with:

```
seize.c:1075 Neither a cgroupv1 (freezer.state) or cgroupv2 (cgroup.freeze) control file found
```

crun's `tfork_save_per_copy_status` never records a copy's cgroup path. That was harmless until WukLab#1 (83dbdba2c,
"Stabilize live tfork source freezing") made the freeze use that field, and WukLab#17 (8b0cbd9fa) extended the same
path to `--copies=1`. With the patch, the nested-fork tests in `setup/nested_tests/` pass: an alpine chain to depth
10, a KDE + Chromium chain to depth 5 (with `RUNG_SETTLE=30`), and the fan-out tests. On 06 they run from
`/mnt/ssd2/vikranth/nested_tests/` via `run_all.sh`. The proper fix is for crun to record the per-copy cgroup path.

## Host setup

SETUP.md has the full steps. The settings that affect results:

- `osw_run.py` switches `kernel.io_uring_disabled` per system, as described above.
- The AENV template comes from the same image, pushed to a local `registry:2` container (`aenv-registry`,
  172.17.0.1:5005). Inside `aenv-server`, `regctl registry set --tls disabled 172.17.0.1:5005` allows plain HTTP, and
  `aenv pull 172.17.0.1:5005/webtop:ubuntu-kde-osworld --name kde-osworld` builds the template.
- The AENV server is set up by `sudo setup/aenv/setup-host.sh` (ublk driver, neighbour, conntrack and pid sysctls)
  and started by `setup/aenv/start-server.sh`. That script runs `aenv-server` in Docker with `setup/aenv/config.toml`,
  keeps its state in `/mnt/ssd2/aenv/env` and writes the CLI credentials. `setup/aenv/fork-smoke.sh` checks that a
  fork keeps in-memory state.
- AENV's guest memory reclaim comes from the guest kernel's boot arguments in `setup/aenv/config.toml`, which are
  AENV's shipped settings: free-page reporting (`page_reporting.page_reporting_order=6`) and DAMON reclaim
  (`damon_reclaim.enabled=Y` and its tuning). Each VM gets 8 GiB (`mem_size_mib = 8192`).
- Two iptables rules in the DOCKER-USER chain let podman containers reach the internet. They were added by hand and
  don't survive a reboot.

## Files

| | |
|---|---|
| `osw_run.py` | the runner; one run is one batch of task groups on one system |
| `a11y_owl_agent.py` | the agent: turns the accessibility tree into a prompt and the reply into pyautogui code |
| `compare.sh` | replays one recording on several systems back to back |
| `analyze.py` | `progress`, `memory` and `clones` summaries of result directories |
| `osw_loop.py`, `train_grpo.py` | the GRPO loop (rollouts on 06) and the LoRA update (on the pod) |
| `pod_serve.sh` | installs vLLM and serves the model on the pod |
| `make_osw_batch.py`, `grpo_batch32v2.json` | the batch builder and the current 32-task batch |
| `desk_osw.sh` | the desktop start script, the same on every system |
| `containers-os4agent.conf` | podman config pinned to os4agent's crun and conmon |
| `criu-baseline.conf`, `seccomp_nopkey.json` | CRIU options and seccomp profile for `stock-criu` |
| `toolspec/` | the shadow TAGE action predictor behind `--spec tage` |
| `SETUP.md` | setup of a new env host, tfork, AENV and the RunPod model server |
| `setup/runpod.sh` | creates, starts and stops the RunPod pod and prints its ssh command |
| `setup/ubuntu-img-kde-osworld.patch` | the desktop image's changes on top of os4agent's KDE webtop |
| `setup/patch_chrome_a11y.py` | the patch to OSWorld's task configs |
| `setup/requirements-06.txt` | the exact venv versions on 06 |
| `setup/clean_tfork_bundles.sh` | removes leftover tfork bundles (their mounts and snapshots) |
| `setup/podman-tfork-cgroup-path.patch` | the change to os4agent described above |
| `setup/aenv/` | AENV host prep, server start with its `config.toml`, and a fork smoke test |
| `setup/nested_tests/` | the nested-fork tests, ported to WukLab main |
| `attic/` | retired code, kept for reference (see below) |

`attic/` holds:

- old task batches, and backups of the files from before the cleanup;
- `drivers/`, `probes/` and `analysis/`: the one-off run scripts, probes and analyses behind the results. For
  example, `probes/aenv_cow.sh` is the AENV guest page-cache test;
- `memcompare/`, an earlier scripted memory comparison that runs without the model.
