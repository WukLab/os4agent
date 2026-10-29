# WebArena trace collection (no fork): checklist

What we record: one epoch of WebArena-Lite shopping rollouts, every rollout in its own freshly set-up environment
(no snapshot / fork), with full timing: environment setup, and per step the observation, the model call (send, first
token, done), the action and the settle wait; the trajectory (messages, replies, actions, page rows); rewards; memory,
vLLM load and network round trip every few seconds. Later these are replayed on forked environments with the recorded
model times, measuring tool and fork time fresh.

## Settings (current)

| | |
|---|---|
| tasks | 32 of WebArena-Lite's 45 shopping tasks: the 35 with no fuzzy_match (no LLM judge needed), 32 picked with seed 0: 29 31 36 37 41 46 56 58 65 66 67 68 72 74 76 77 78 82 86 93 94 95 103 104 109 118 119 120 121 129 148 162 (default of `wa_record.py --tasks`) |
| rollouts per task (group) | 8 |
| batch (groups at once) | 4 groups = 32 rollouts per wave, 8 waves; all rollouts of a wave start together, the wave ends when the last one ends |
| max steps | 15; 1 s sleep after each action (`wa_run.py`'s `sleep_after_execution`) |
| policy | Qwen3-VL-8B-Instruct, dense (no LoRA: one epoch is pure inference; vLLM LoRA had errors on H100), temperature 1.0, top_p 0.9, max 512 tokens, streamed |
| model server | **one** RunPod H100 SXM 80GB (`gpuCount 1`), vLLM, served as `qwen3vl8b`, ssh tunnel to localhost:8100 |
| environment | `localhost/wa-shop-orig-browser:latest` (original WebArena shopping image + Chromium 102) under podman, storage on the NVMe btrfs (`/mnt/data/btrfs/podman`) |
| agent | the teammate's text agent (`~/RL-tool-spec/webarena/wa_agent.py`, unchanged prompt, rows and parser; `wa_run.py`'s action executor) |
| scoring | `lite_eval.py`; the Verified-style answer is turned into Lite's string (retrieved_data joined with ", ", or the status) |
| sampling | memory, vLLM metrics every 5 s; RTT every 30 s |

## Before the run (host)

- [ ] `df -h / /mnt/data/btrfs`: root ≥ 50 GB free; btrfs has room for a wave (pilot: measure the write per wave).
- [ ] No other experiments on the box (GPUs idle, no other containers): `nvidia-smi`, `docker ps`, `podman-tfork.sh ps -a`.
- [ ] The image is in podman's store: `podman-tfork.sh images` lists `localhost/wa-shop-orig-browser:latest`.
- [ ] Runner venv `/mnt/data/ssd1/yutong_data/venv-pw1.44.0` (Playwright **1.44.0**: 1.64 cannot drive Chromium 102),
      with nltk, openai, requests. Root has its own tokenizer data in `/root/nltk_data` (NLTK refuses data owned by
      another user; without it every reward is unscored).
- [ ] `podman-tfork.sh` sysctl preflight: `kernel.io_uring_disabled=2`, `fs.inotify.max_user_instances=524288`
      (runtime only; redo after a reboot: `agents/webarena_rl/setup/build_tfork.sh` stage 6, or the README's sysctls).
- [ ] Dry run with the mock (no GPU, 1 min): see Commands.

## Model server (RunPod)

- [ ] Price and stock read first (`list-gpu-types`), **one** H100 SXM 80GB, secure cloud, image
      `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`, 200 GB container disk, port 22, `minCudaVersion 12.8`,
      `PUBLIC_KEY` = this host's `~/.ssh/id_ed25519.pub` (it is not among the account's registered keys).
- [ ] Direct ssh (not the ssh.runpod.io proxy, which cannot forward ports): `ssh -p <port> root@<ip>`.
- [ ] Serve dense (the teammate's `agents/osworld_rl/pod_serve.sh` without the three LoRA flags):
      vLLM 0.11.0 + transformers 4.57.1, `--max-model-len 32768 --limit-mm-per-prompt '{"image":0,"video":0}'
      --enable-prefix-caching --gpu-memory-utilization 0.9`.
- [ ] Tunnel: `ssh -f -N -L 8100:localhost:8000 -p <port> root@<ip>`; `curl -s localhost:8100/v1/models` lists
      qwen3vl8b; `curl -s localhost:8100/metrics | grep num_requests` works (vllm.jsonl needs it).
- [ ] Record the pod id, GPU, data center and hourly price in NOTES.md.
- [ ] **Delete the pod as soon as the traces are collected** (and confirm with a read that it is gone).

## Commands

```
cd agents/webarena_rl
P=/mnt/data/ssd1/yutong_data/venv-pw1.44.0/bin/python
# dry run, no GPU: the teammate's scripted mock (non-streaming)
(cd ~/RL-tool-spec/webarena && $P -I mock_llm.py 8199 &)
sudo -n env LLM_URL=http://127.0.0.1:8199/v1 $P wa_record.py --result-dir /mnt/data/btrfs/wa_traces/dryrun_mock \
    --tasks 29,31 --rollouts 2 --groups-at-once 2 --stream 0 --model mock
# pilot: 1 group (8 rollouts) against the H100
sudo -n env LLM_URL=http://127.0.0.1:8100/v1 $P wa_record.py --result-dir /mnt/data/btrfs/wa_traces/pilot_h100 \
    --tasks 29 --groups-at-once 1
# full run: 32 tasks x 8, 4 groups per wave. Through systemd, NOT `sudo ... setsid nohup ... &` from a shell (sudo
# passes the shell's hangup on: the first launch died 23 s in)
sudo -n systemd-run --unit=wa-record-lite32 --collect -p WorkingDirectory=$PWD \
    -p StandardOutput=file:/mnt/data/btrfs/wa_traces/lite32_h100.log -p StandardError=file:/mnt/data/btrfs/wa_traces/lite32_h100.log \
    --setenv=LLM_URL=http://127.0.0.1:8100/v1 --setenv=NLTK_DATA=/root/nltk_data --setenv=SUDO_UID=$(id -u) --setenv=SUDO_GID=$(id -g) \
    $P $PWD/wa_record.py --result-dir /mnt/data/btrfs/wa_traces/lite32_h100
systemctl is-active wa-record-lite32           # watch; stop with: sudo systemctl stop wa-record-lite32
# leftover environments after a crash (kills first, then removes; podman removes ~8 s per container)
sudo bash setup/cleanup_recording.sh wa-lite32-h100
```

## Pilot checks (before the full run)

- [ ] Every rollout has `result.json` with a reward (not None) and no `error`; `eval_error` absent.
- [ ] `steps.jsonl`: `t_first_token` < `t_llm_done` (streaming works), prompt / completion tokens present.
- [ ] `vllm.jsonl` has `vllm:num_requests_running` etc. (not just `t`); `rtt.jsonl` round trips are small.
- [ ] `mem.jsonl` has every live environment; `events.jsonl` has setup / rollout / teardown per wave.
- [ ] btrfs used before vs after a wave (the write per environment); containers all removed after the wave.
- [ ] Replies parse (few `invalid` actions); answers look like answers.

## After the run

- [ ] Counts: 256 `result.json`, rewards per task, errors per wave.
- [ ] No containers left (`podman-tfork.sh ps -a`), no tfork bundles.
- [ ] **RunPod pod deleted** (read back: 404 / not listed).
- [ ] Results and commands logged in NOTES.md; traces stay in `/mnt/data/btrfs/wa_traces/`.

## Pitfalls seen so far

- `podman pull docker-daemon:` spools the whole image to `image_copy_tmp_dir` (default /var/tmp on the root disk);
  ours points at the btrfs disk. Prefer `setup/import_to_podman.py`.
- The old btrfs disk was an HDD; podman's unpack of the image's 195k small files ran at 20 MB/s. Now on NVMe.
- Docker's overlay copies a whole file into the container on its first write (the image's 3.1 GB Magento debug.log;
  emptied in the Dockerfile). btrfs snapshots copy changed blocks only.
- Waiting loops with `pgrep -f <pattern>` match their own command line; wait on a PID instead.
- `PODMAN_TFORK_NO_REAP=1` keeps successful clones' bundles too; use it only when a failure needs logs.
- Magento's search box: Playwright `fill` appends to the query already in it (any Chromium version).
- Forked Chromium renderers crash on the next navigation for some page states (step 3 in NOTES.md); irrelevant here
  (no fork), relevant for the replay.
- `kill -0 <pid>` from a normal user on a root process fails (EPERM) even when it is alive: a watcher built on it
  "finishes" at once. Watch the run with `systemctl is-active <unit>` or `ps -p <pid>`.
- Before deleting a run's directory or relaunching, check that no recorder still runs
  (`ps -eo pid,cmd | grep "[p]ython.*wa_record.py"`); use a new `--result-dir` (container names derive from it).
