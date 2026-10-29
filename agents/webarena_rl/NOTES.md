# Notes (steps, commands, results, mistakes)

## 10-28. Benchmark and design decisions

- Benchmark switched from WebArena-Verified to the original WebArena shopping image (`shopping_final_0712`) with
  WebArena-Lite's 45 shopping tasks: the RL papers on WebArena (WebRL, WebAgent-R1) use Lite and the original images.
- Option B: the site and a headless Chromium in one container, forked together (rationale in PLAN.md).
- Local inference servers stopped (Qwen3-VL-8B on GPU0 :8004, Qwen3-4B on GPU1 :8002) so nothing else runs during
  the experiments.

## 10-28. Step 1a: image `wa-shop-orig-browser` and the CDP test

Build (44 s):
```
cd agents/webarena_rl/image && docker build -t wa-shop-orig-browser:latest .
```
- `FROM shopping_final_0712:latest` (Alpine 3.16.5) + Alpine's `chromium` 102.0.5005.182 + `font-noto` + user
  `chrome` (uid 1999); Chromium as a supervisord program (`chromium.ini`): headless, `--no-sandbox`,
  `--disable-dev-shm-usage`, DevTools on 0.0.0.0:9222, profile in /tmp/chrome-profile.
- `apk add` always exits 1 in this image: the image's glibc compatibility package (glibc 2.35-r0) has no apk source
  any more ("APK unavailable, skipped"). Chromium installs fine; the Dockerfile checks `chromium-browser --version`
  instead of apk's exit code.
- The first Dockerfile (on the Verified image) failed the same way; it was replaced.

Test (`test_image.py`, ~1.5 min, docker only):
```
/mnt/data/ssd1/yutong_data/venv-pw1.44.0/bin/python agents/webarena_rl/test_image.py
```
Checks: site answers inside the container; Chromium runs under supervisord; CDP answers from the host;
`connect_over_cdp`; form login; the agent's page extraction (`wa_agent.EXTRACT_JS`, 139 rows on the home page); a
category click; a search; typed text in a field; disconnect + reattach keeps the page, the typed text and the login.

Result: **ALL PASSED (twice) → option B.** Timings: MySQL up 4.5 s, base URL + cache flush 20.4 s, first page 20 s,
login 3.7 s, extraction 3.7 s, CDP connect < 0.1 s. Chromium (6 processes) RSS ~750 MiB after these steps.

Findings and mistakes:
- **Playwright version:** Playwright 1.64 cannot drive Chromium 102: its injected script calls
  `element.checkVisibility()` (Chromium 105+), so `fill` fails with `TypeError: element.checkVisibility is not a
  function`. Playwright 1.44.0 works. The WebArena runner must use Playwright 1.44.0 (venv
  `/mnt/data/ssd1/yutong_data/venv-pw1.44.0`; 1.40.0 also tried, same behaviour).
- **Magento's search box:** `fill` on the search combobox appends to the query already in it ("headphones" +
  "new text") instead of replacing it. Same with Chromium 156 (Playwright 1.64 on the host, the container's nginx as
  proxy), and `fill` replaces correctly on a plain page with Chromium 102, so this is Magento's widget, not the old
  browser; agent runs on modern Chromium behave the same. My first input check used that box and failed (once
  passing by timing luck); the check now uses the empty newsletter field.

## 10-28. Step 1b: WebArena-Lite tasks and evaluator

- `tasks/lite_shopping.json`: the 45 shopping tasks of WebArena-Lite, unchanged (THUDM VisualAgentBench @9055fc2,
  `VAB-WebArena-Lite/new/test_webarena_lite.raw.json`, sha256 5e901fc1d7155bc0…; local clone
  `/mnt/data/ssd1/yutong_data/webarena_src/VisualAgentBench`). All need login; none needs a reset.
  Eval types: string_match 23 (must_include 13, fuzzy_match 8, exact_match 2), program_html 11, url_match 10
  (all "GOLD in PRED"), url_match + program_html 1.
- `lite_eval.py`: port of Lite's `evaluators.py` + the one helper the shopping tasks use, without the visualwebarena
  package. Same logic, clean-ups and 3 s sleep. Forced differences: async Playwright page inside the environment
  (`__SHOPPING__` = http://localhost); the latest-order helper calls Magento's REST API with fetch() from that page;
  the fuzzy_match judge is any OpenAI-compatible endpoint instead of GPT-4-1106-preview (same prompt and parsing).
  10 tasks need it (8 string, 2 page); without a judge they score None.
- Runner venv `/mnt/data/ssd1/yutong_data/venv-pw1.44.0` now also has nltk 3.10.4 (+ punkt_tab data in the venv),
  openai, requests.
- `test_lite_eval.py` (`… /venv-pw1.44.0/bin/python test_lite_eval.py`, ~3 min): **ALL PASSED**
  - equiv: Lite's original `evaluators.py` (heavy imports stubbed) vs the port on string / URL scoring: 6,630
    comparisons (every recorded answer and final URL × every task), 0 differ.
  - recorded: the 255 step-133 Lite rollouts (Qwen3-8B, original image): of the 181 scored by string / URL, 22 score
    1 (12%); 74 need program_html or the judge.
  - live (fresh container): REST helper finds the latest order; all 12 program_html tasks score 0 (the 2 fuzzy ones
    None); goals done by hand score 1 for wishlist (120), newsletter (121), cart (103), address (129).
- Mistakes: test stub passed `PseudoPage` twice; `requests` missing (imported by the original); tasks with
  `reference_answers: null` (program_html only) broke a dict lookup. All fixed before the passing run.

## 10-28. Step 2: tfork on wuklab-08

User decision: try tfork before the no-fork baseline (step 1c deferred).
```
bash agents/webarena_rl/setup/build_tfork.sh        # logs in /mnt/data/ssd4/yutong/tfork_build/
```
- All stages ok in 3 min (05:33–05:36): submodules; apt podman; `criu/build.sh` (apt deps, criu, libcriu, kernel
  modules vma_cherrypick, criu_capbypass, pkey_state, reparent_task insmod'ed); `crun/build.sh`; `conmon/build.sh`;
  `podman/build.sh`.
- Sysctls set for this boot only (not in /etc/sysctl.d; values before in `sysctl_before.txt`):
  kernel.io_uring_disabled 0 → 2, fs.inotify.max_user_instances 128 → 524288,
  kernel.apparmor_restrict_unprivileged_unconfined 1 → 0. fs.nr_open (2147483584) and max_user_watches (1048576)
  already met the README's minimums, so they were left alone (setting nr_open would have lowered it).
- Podman storage on btrfs: `/mnt/data/btrfs/podman/storage.conf` (driver btrfs, graphroot
  `/mnt/data/btrfs/podman/storage`, runroot `/mnt/data/btrfs/podman/run`). Podman config pinned to this checkout's
  conmon and crun: `agents/webarena_rl/containers-os4agent.conf`. Every podman call:
  `sudo env CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf CONTAINERS_CONF=<that file> ./podman-tfork.sh ...`
- Wiring checks (README "Verify"): 4 modules loaded; crun `tfork` verb, conmon `--tfork`, podman
  `clone --live/--copies`; podman info: in-tree conmon and crun, cgroupfs, cgroup v2, k8s-file, btrfs graphroot.
  Stock kernel (no page-cache-CoW kernel, as on 06).
- Smoke: alpine 3.20 source with an in-memory counter loop; `container clone --live --copies=2 --persistent=async
  --tfork-tcp-close --tfork-overlay-btrfs` → rc 0 in 1.3 s; both copies running and counting on from the source's
  value. Test containers removed, no leftover tfork bundles.
- Not applied: `agents/osworld_rl/setup/podman-tfork-cgroup-path.patch` (applies cleanly; needed only for a clone of
  a clone).
- Mistake: my first smoke command removed a possibly stale container with `rm -f` through a shell variable; a safety
  check blocked it. Rewritten without the removal (nothing to remove) and with explicit container names.

## 10-28. Image into podman; disks swapped (user decisions)

- `podman pull docker-daemon:wa-shop-orig-browser` spools a full `docker save` tarball at ~28 MB/s (≈1 h). Its
  default temp dir /var/tmp is on the root disk: after 11 min it had written 19 GB there with the root disk at 41 GB
  free. Mistake: not checking where it spools before starting. Killed it, removed the partial file; podman's
  `image_copy_tmp_dir` is now `/mnt/data/btrfs/podman/tmp` (in `containers-os4agent.conf`).
- Size (user question): of the image's ~63 GB, 45.1 GB is Magento's resized-image cache
  (`pub/media/catalog/product/cache`), 5.8 GB product photos, 3.8 GB /usr, 3.6 GB MySQL, 3.1 GB old logs, 0.85 GB
  Elasticsearch. WebArena-Verified's 13 GB image drops the cache and the logs. Kept the full image (user choice): with
  the cache gone, each forked copy would resize and write its own images while browsing (private memory, writes, CPU),
  unlike the original, where they are read-only files shared through the page cache.
- `setup/import_to_podman.py`: docker run the image idle (entrypoint sleep, no network), tar its rootfs from
  /proc/<pid>/root straight into `podman import` with the image's entrypoint/cmd/workdir/env/ports. tar ~700 MB/s.
- The old `/mnt/data/btrfs` was `sdb`, a 7200-rpm HDD (Seagate ST1000NX0443): podman's layer unpack of 195k small
  files ran at ~20 MB/s, disk 98% busy. Stopped (podman needed SIGKILL; a nested mount
  `/mnt/data/btrfs/podman/storage/btrfs` had to be unmounted first).
- User decision: format ssd2 (NVMe Samsung MZ1LV480HCHP, `/dev/nvme0n1p1`, 391 GB of data, deleted at the user's
  explicit go after seeing the listing) as btrfs for `/mnt/data/btrfs`; sdb reformatted ext4. Now:
  - `/dev/nvme0n1p1` btrfs (label nvme-btrfs, UUID f898bc33-…) at `/mnt/data/btrfs`, `noatime,compress=zstd`;
  - `/dev/sdb1` ext4 (label hdd, UUID fb5bf7d0-…) at `/mnt/data/hdd`;
  - `/mnt/data/ssd2` no longer exists; `/etc/fstab` updated, old one at `/etc/fstab.bak-2026-10-28`.
  - ssd2 could only be unmounted after the user left a tmux shell whose cwd was on it.

## 10-28. Image on NVMe; step 3, first tfork of the WebArena environment

- `setup/import_to_podman.py` into the NVMe btrfs: 06:58 → ~07:34 (spool 64.7 GB at ~175 MB/s; podman's staging copy
  ~80 MB/s, CPU-bound; unpack ~5 GB/min). `localhost/wa-shop-orig-browser:latest`, 64.7 GB; temp files removed.
- `test_fork.py` (source as osw_run.py starts one; site setup; CDP login, product page, text typed into the
  newsletter field; `podman exec src true`; `clone --live --copies=2 --persistent=async --tfork-tcp-close
  --tfork-ghost-limit=64M --tfork-overlay-btrfs`; /etc/hosts refill; per-copy checks). Clone keeps failed bundles
  (`PODMAN_TFORK_NO_REAP=1`) and copies their logs to `/mnt/data/ssd4/yutong/tfork_build/failed_clones/`.
- Result: the clone works (2 copies in 10–18 s); the source keeps serving; in each copy the site answers, CDP
  reattaches to the same page, the unsubmitted typed text and the login survive, `fetch('/')` from the page works,
  and a **new tab works**. But **the forked renderer crashes on its next navigation or reload** (`Page crashed`;
  dmesg `traps: chrome[...] trap int3`, a Chromium CHECK failure), in every copy.
- Variants tried (Chromium restarted in place in the source before the fork):
  - shared memory in /dev/shm (no `--disable-dev-shm-usage`) + tmpfs /tmp: same crash;
  - `--disable-gpu-compositing`: same crash;
  - `--in-process-gpu`: clone fails (CRIU `skqueue: Control messages in queue, not supported`, an SCM_RIGHTS
    message in flight at the freeze); `--single-process`: clone fails the same way in 3 of 3 attempts.
- Memory, one environment (source before the fork: PSS 2,071 MiB, anon 1,719, RSS 2,634, cgroup 3,254 MiB). After the
  fork: source PSS 974, copies 667 / 650 MiB PSS (anon ~620, file ~35, shmem 4); copies' cgroups charged 545 / 473
  MiB; source cgroup 4,803 MiB.
- Cleanup: no containers left; the 4 kept failed-clone bundles removed with `agents/osworld_rl/setup/
  clean_tfork_bundles.sh` (its "no containers" check uses osworld_rl's podman config, whose paths do not exist here,
  so `podman ps` errored and the check passed silently; there were none).

## 10-28. Is the renderer crash the old Chromium? (option 1, user decision)

`test_chrome_fork.py`: a tiny local site (python http.server, two pages, an input) + headless Chromium with CDP,
same podman settings and tfork flags, no Magento; checks per copy: reattach, typed text, reload, navigate, new tab,
dmesg `trap int3`. Modern browser: `mcr.microsoft.com/playwright/python:v1.44.0-jammy` (Chromium 125.0.6422.26,
pulled into the btrfs store, 54 s).

| browser | page at fork time | result |
|---|---|---|
| Chromium 125 | static | all pass, both copies |
| Chromium 102 (our image, started directly) | static | all pass, both copies |
| both | CSS animation + requestAnimationFrame loop (verified running: counter 6 → 37 in 0.5 s) | all pass |

So the **browser version is not the cause**. Back on the WebArena environment (`test_fork.py --park-url`):

| page at fork time | copy 0 | copy 1 |
|---|---|---|
| Magento product page (logged in), 4 runs | crashes on next navigation | crashes |
| about:blank | crashes | passes |
| http://localhost/robots.txt | passes (all checks, incl. private wishlist writes) | passes |

- The crash depends on the page's state at fork time (and is not certain); no message in Chromium's log even with
  `--enable-logging=stderr --v=0` (a bare CHECK crash, as in release builds).
- Mistake: my first animated page had a JavaScript syntax error from shell quoting (`getElementById(\"n\")`), so its
  rAF loop never ran; caught by checking the generated command; fixed and re-verified with a counter check.
- Containers removed. `PODMAN_TFORK_NO_REAP=1` on every clone also keeps successful clones' bundles (6 left); removed
  with `clean_tfork_bundles.sh` (0 bundles, 0 mounts). Set it only when a failure needs its logs.

## 10-28. Trace recorder (no fork) and the plan for recording

User decisions: record one epoch with timing only, no snapshot / fork (replay on forks later); 32 tasks × 8 rollouts,
batch 32 (4 groups per wave; 256 at once does not fit on this host without forking: ~615 GB anon, ~1.7 TB of start-up
writes); podman on the NVMe btrfs (block-level CoW, instead of docker overlay's whole-file copy-up); one H100 on
RunPod, dense Qwen3-VL-8B (no LoRA), deleted after the traces are collected.
- Disk writes per container (docker probe): 3.56 GB 30 s after start, 3.1 GB of it Magento's shipped
  `var/log/debug.log` copied up on its first append. Dockerfile now empties the old Magento logs (new layer, 8 KB):
  0.81 GB after start, 3.86 GB after setup + 4 pages (more copy-ups: nginx access.log 217 MB, MySQL redo log 96 MB,
  …). Not chased further (user decision): recording runs on btrfs, where appends copy blocks, not files.
- Tasks: the 35 Lite shopping tasks without fuzzy_match, 32 picked with seed 0 (list in TRACE_COLLECTION.md).
- `wa_record.py`; `TRACE_COLLECTION.md` (checklist for this and future runs).
- Dry run with the teammate's mock LLM (2 tasks × 2): setup ~32 s per environment (container 0.3 s, MySQL 2.6 s,
  base URL + flush 4.9 s, first page 23.8 s, login 28 s, start page 31.8 s); steps, chat, result, mem, events written;
  containers removed. Mistake caught: running as root, NLTK refused the tokenizer data owned by my user, so every
  reward failed with `eval_error` and showed as 0. Fixed: root's own copy in `/root/nltk_data`; an evaluation error
  is now reward None, never 0. Re-run: all 4 scored, no eval_error.

## 10-28. RunPod model server for the recording

- Price/stock read (list-gpu-types, secure, 08:5x UTC): H100 SXM 80GB $3.99/hr LOW in AP-IN-1 and CA-MTL-1; H100 NVL
  94GB $3.19/hr LOW in US-KS-2. Create of H100 SXM in CA-MTL-1 failed (stock gone between read and create; no pod).
  User decision: H100 NVL in US-KS-2.
- Pod **h1ba1ods2gsjw9** "wa-trace-h100": 1× NVIDIA H100 NVL (95,830 MiB), secure, US-KS-2, $3.19/hr, created
  2026-10-28 08:54:27 UTC; image runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404, 200 GB container disk, port
  22/tcp only, PUBLIC_KEY = this host's key; direct ssh `ssh root@216.81.245.58 -p 27827`. **Delete after the traces.**
- Serving: `setup/pod_serve_dense.sh` (the teammate's pod_serve.sh without the LoRA flags), vLLM 0.11.0 +
  transformers 4.57.1, qwen3vl8b on :8000, gpu-memory-utilization 0.9.
- 09:01 serving (7 min after create): weights 3.7 s, KV cache 62.5 GiB = 455,216 tokens. Tunnel
  `ssh -f -N -L 8100:localhost:8000 -p 27827 root@216.81.245.58`; RTT through it ~145 ms (Kansas ↔ here); first
  streamed request TTFT 2.3 s (cold).
- Pilot `/mnt/data/btrfs/wa_traces/pilot_h100` (task 29 × 8, one wave): 8 environments set up in 32 s, 0 failed;
  rollouts ~9 s, 3 steps each (type search, click, done), 0 step errors, all scored (reward 0: task 29's check needs
  the final page to show "mouth guard"; the agent answered from a dental-guard page). Step medians: observe 0.09 s,
  TTFT 0.24 s, decode 0.42 s, action 1.15 s, settle 1.10 s; prompt 2,843 tokens, completion 47. btrfs +1.7 GB peak
  for 8 environments (~215 MB each, vs ~4 GB under docker overlay); teardown 64 s. vllm.jsonl at 5 s missed every
  ~0.5 s request: vLLM sampling now every 1 s (`--vllm-sample-s`).
- Full run started 09:04:34: `/mnt/data/btrfs/wa_traces/lite32_h100` (32 tasks × 8, 4 groups per wave, 8 waves).
- Mistake: the first full-run launch (`sudo … setsid nohup python … &` from my tool shell) died 23 s in, silently:
  sudo sat above setsid and passed the shell's hangup on. It left 24 wave-0 containers running (removed, ~2.5 min:
  podman removes one at a time on its storage lock, ~8 s per container; empty run dir removed). Fixes:
  - the run now goes through systemd (`sudo systemd-run --unit=wa-record-lite32 --collect -p WorkingDirectory=…
    -p StandardOutput=file:… --setenv=LLM_URL=… --setenv=NLTK_DATA=/root/nltk_data --setenv=SUDO_UID=… …`);
    `wa_record.py` also ignores SIGHUP;
  - teardown runs in the background (kill all, then one `podman rm` for the wave) while the next wave sets up;
    the run waits for all teardowns at the end;
  - `setup/cleanup_recording.sh [prefix]` kills then removes leftover recording containers.
- Full run relaunched 09:09:15 as systemd unit `wa-record-lite32`.
- **Mistake (worse than the first): the first launch had NOT died.** My watcher waited with `kill -0 <pid>` on a
  root process from my user, which fails with EPERM whether or not the process exists, so it "finished" at once and I
  concluded the recorder was dead (its log looked frozen). I then removed its 24 wave-0 containers, deleted its run
  dir and log while it ran, and started a second recorder (systemd) into the same dir: two recorders creating the
  same container names (`name … is in use`), wave 0 "setup done" twice. Found at 09:14 from the doubled events.
  Stopped both (systemd unit; the first by its PID after a cmdline check), killed the 32 leftover containers
  (removal in the background as unit `wa-cleanup-lite32`), set the broken dir aside as
  `/mnt/data/btrfs/wa_traces/lite32_h100_broken`. Clean run under a new name (no container-name clashes):
  unit `wa-record-lite32-r2`, `/mnt/data/btrfs/wa_traces/lite32_h100_r2`, started 09:15:06, one recorder (checked
  with `ps`). Rules: watch root processes with `systemctl is-active` / `ps -p` / `sudo kill -0`, never plain
  `kill -0`; before deleting a run's files, check no process still writes them.
- Run r2 stopped at the user's request (09:20; 24 containers killed and removed, ~8.0 s each one at a time; dir set
  aside as `lite32_h100_r2_stopped`). Its wave-0 setup had stalled behind the removal of r1's 32 containers.
- Removal cost (user asked whether stock podman would help; stock podman 5.7.0 + conmon 2.1.13 + runc vs ours 5.8.2):
  alpine `rm -f -t 0`: ours 0.19–0.21 s, stock btrfs 0.30 s, stock overlay 0.30–0.35 s. WebArena container: created
  but never started 7.9 s, killed then removed 8.1 s, running 8.2 s; `kill` 0.26 s. So it is the storage, not the
  podman build: removing a btrfs-driver container walks its ~200k-file rootfs (my reading of containers/storage's
  btrfs driver, which searches for nested subvolumes before deleting; not profiled). Stock podman shares that code.
- Fix (user choice): teardown = kill only; containers removed after the run (`killed_containers.txt`,
  `setup/cleanup_recording.sh`), after the H100 is deleted. Run r3: unit `wa-record-lite32-r3`,
  `/mnt/data/btrfs/wa_traces/lite32_h100_r3`, started 09:27:11 on a clean host (0 recorders, 0 containers).
- **Run r3 done** 09:27:11 → 09:59:33: 256/256 rollouts, 8 waves, 0 setup failures, ~3.8 min per wave
  (setup ~2:15, rollouts ~1.5 min, kill 5 s). 12 rollouts ended in `Page.evaluate: Execution context was destroyed`
  (page mid-navigation at observe; tasks 41:3, 68:3/6/7, 77:1/2/3, 86:0/1/2/3/7). Fix: `read_page()` retries up to 3
  times after waiting for domcontentloaded. Re-recorded with `--only` into
  `/mnt/data/btrfs/wa_traces/lite32_h100_r3_redo` (one wave of 12, 10:01–10:02:51): 12/12 scored, no errors (1
  success). Caveat: those 12 ran 12 at a time, not 32.
- **Pod h1ba1ods2gsjw9 deleted** ~10:04 (delete-pod 204; get-pod 404). Ran 08:54:27–~10:04, ~70 min × $3.19/hr ≈ $3.7.
  Saved first: `/mnt/data/btrfs/wa_traces/vllm_server_h100nvl.log`; driver 595.91.07. Tunnel gone with the pod.
- Killed containers (268) removed after the run as unit `wa-cleanup-r3` (~8 s each, no GPU waiting).
- `summarize_traces.py <run> [<redo>]` → `<run>/summary.md`. With the redo merged: 256 rollouts, rewards 63 × 1.0 /
  193 × 0.0, no errors; stop: done 155, max_steps 101; 2,254 steps. Per step median (share of step time): observe
  0.08 s (5.1%), send → first token 0.36 s (14.7%), decode 0.52 s (22.6%), action 0.71 s (26.3%), settle 1.03 s
  (31.4%); model 37.3% of step time. Prompts median 2,172 tokens, completions 47. Site setup per environment
  32.4 s median (MySQL 5.4, base URL + flush 3.1, first page 23.0), login 11.2 s and start page 9.4 s after the
  barrier (32 at once). Rollout median 31 s (p90 65 s). RTT to the pod 0.194 s median (in the model times).
  Success per task: 8/8 on 41, 46, 66, 109, 119, 120, 148; partial on 94 (1), 95 (2), 103 (2), 121 (2); 0 on the rest.

### Integrity check of the recording (2026-10-28, after the reboot)

- `python3 check_traces.py /mnt/data/btrfs/wa_traces/lite32_h100_r3 /mnt/data/btrfs/wa_traces/lite32_h100_r3_redo` → INTACT:
  256 / 256 (task, k) rollouts (12 from the redo), 2,254 steps; every result.json / steps.jsonl / chat.jsonl parses;
  steps 1..n match result.json; per-step timestamps ordered; every rollout scored, no errors; mem / vllm samplers cover
  the run (largest gap 8.6 s / 6.8 s at a 5 s period), rtt 64 samples, events has 8 waves and run_done.
- Check script mistake: it first expected role-tagged messages in chat.jsonl; chat.jsonl is one record per step
  (messages, response, action, rows, url, t). One step (redo 86__g3 step 11, a made-up URL) has an empty rows list: real.
- Cleanup `wa-cleanup-r3` finished: 0 containers; btrfs 59 GB used / 386 GB free. The box rebooted (kernel 7.0.0-38):
  the tfork sysctls are back to defaults (redo `setup/build_tfork.sh` stage 6 before using podman-tfork again).

### Fork crash vs. memory protection keys (2026-10-28, after the reboot; host now 247 GiB RAM)

- Reboot → kernel 7.0.0-38: `setup/after_reboot.sh` (new) rebuilds the 4 CRIU modules for the running kernel (make clean,
  criu/build.sh), insmods them, sets the tfork sysctls, runs podman-tfork's preflight. OK in 32 s.
- Teammate's Chromium fixes (CRIU_TFORK_IMPLEMENTATION.md §18, dothyt/os4agent af7e52e61) are in this checkout's CRIU
  source (squashed history, so not the commit): 18.1 servicefd busy target, 18.6 EXDEV ghost fallback, 18.8 host userns
  id; runs already use --tfork-tcp-close / --tfork-ghost-limit. Their "Aw, Snap! SIGTRAP" fix was stock CRIU dropping
  pkeys (seccomp_nopkey.json); CPU here (Xeon Gold 5218) has pku/ospke, so tested whether pkeys cause our crash.
- test_fork.py additions: `--seccomp nopkey`, dmesg `trap int3` count, per Chromium process the number of VMAs with
  smaps ProtectionKey != 0, `--log-tag` (clone at CRIU_TFORK_LOG_LEVEL=4 with PODMAN_TFORK_NO_REAP=1, CRIU logs to
  /mnt/data/ssd4/yutong/tfork_build/clone_logs/<tag>/).
- Mistake: the first version removed the clone's bundle right after the clone; the bundle holds the copies' live root
  filesystems, so the copies lost /etc (run 1 void; it also copied 14 GB of Magento logs, deleted). Now only
  crun-tfork.log and img/*.log are copied and the bundle is removed after the copies.
- Result (product page, 2 copies each):

| run | pkey_state in dump | VMAs with a key ≠ 0 (src / copies) | copies crashed | trap int3 |
|---|---|---|---|---|
| unconfined | ready; 26 procs map=0x1 | 0 / 0 | 2 of 2 (next goto: "Page crashed") | 2 |
| nopkey | ready; 26 procs map=0x1 | 0 / 0 | 2 of 2 | 2 |

- So pkeys are not the cause: Chromium 102 allocates none (map=0x1 = only key 0), pkey_state works.
- All 4 crashes are at the same offset in the chrome binary: `chrome[9919d8b, base+8d95000]`, ip ends in ...ad8b:
  one deterministic CHECK. Next: symbolize offset 0x9919d8b (Alpine chromium 102 debug symbols) or catch the renderer's
  stderr / crash dump to read the CHECK message.

### Newer Chromium for the fork crash (2026-10-28)

- Two-container test (`test_browser_fork_remote.py`: site not forked, browser container forked alone) is blocked by the
  host firewall: nftables `inet filter input` policy drop (only ssh :456 and lo), Docker's FORWARD policy DROP with
  br_netfilter on: podman containers reach neither each other nor the host. Opening it was refused by the permission
  check (host firewall: the user's call). Not run.
- Instead (user's pick): `setup/build_chromium_bundle.sh` (docker alpine:3.20, which has outbound network) makes a
  self-contained Chromium 131.0.6778.108 + socat under /opt/chr (143 libs, its own musl loader, patchelf'd interpreter
  and rpath; 357 MB tar in /mnt/data/ssd4/yutong/tfork_build/chr_bundle/). Runs in the 3.16 image; renderer maps only
  /opt/chr libs. `test_fork.py --chrome-bundle <tar>`: 131 with --headless=old on 127.0.0.1:9221 (131 ignores
  --remote-debugging-address) + supervisord socat relay 0.0.0.0:9222, relay restarted in each copy.
- Result: unusable before any fork. The 131 renderer segfaults (null deref, always chromium+0xa7daebc) on text input:
  Playwright fill() on any input (also a data: page), and click + keyboard.type into the login password field.
  Not HOME (supervisord user= keeps HOME=/root), not the 102-made profile, not --password-store=basic. Keyboard typing
  into a plain field works. After a renderer crash the browser's CDP hangs until a restart. Fork behaviour of 131 not
  measured. (put_text() in test_fork.py; keyboard.type has no timeout: the last run hung 15 min, stopped by PID.)

### Chromium 142 bundle (Alpine 3.22): the fork crash is gone (2026-10-28)

- `bash setup/build_chromium_bundle.sh 3.22` → Chromium 142.0.7444.59 (402 MB tar). Only /opt/chr is written; the site's
  3.16 packages are untouched.
- Needed for 142 under supervisord: plain `--headless` (old headless left the binary after 131: `--bundle-headless`),
  `environment=HOME="/home/chrome"` (supervisord's user= keeps HOME=/root; the crashpad handler then has no database and
  Chromium exits in a loop), CDP on 127.0.0.1:9221 + socat relay on :9222. In copies supervisorctl has no socket
  (/run/supervisord.sock missing), so the relay is restarted with `podman exec -d … socat`.
- 142 takes Playwright 1.44's fill() (131's renderer segfaulted on it).
- `test_fork.py --chrome-bundle chr-142.0.7444.59.tar`: ALL PASSED with 2 copies (clone 15.1 s) and with 4 copies
  (30/30 checks, clone 20.4 s): reattach, typed text, still logged in, search, private wishlist write, 0 trap int3,
  0 segfaults. Same test with 102: both copies crash on the next navigation.
- Memory (PSS MiB): source 2,083 (102) vs 2,260 (142); per copy after the fork 635 (102, 2 copies) vs 695 (142,
  2 copies) and ~460 (142, 4 copies).
- Not done: baking the bundle into the image (new Dockerfile layer, re-import), Playwright upgrade question, and the
  recorded traces were made with 102 (accessibility rows may differ under 142: re-record or tolerate mismatches).

### Image with Chromium 142 baked in (2026-10-29)

- `bash agents/webarena_rl/setup/build_image_chr142.sh`: docker build of `image/Dockerfile.chr142` (FROM
  wa-shop-orig-browser + ADD the 142 bundle + `image/chromium142.ini`: Chromium on 127.0.0.1:9221 with HOME set, no
  --disable-dev-shm-usage, supervisord program cdp-relay = socat 0.0.0.0:9222) in <1 min, then import_to_podman.py
  (23:54 → 00:47, 53 min). Podman store: `localhost/wa-shop-browser142:latest` 61.9 GB (the old podman copy of
  wa-shop-orig-browser, 64.7 GB, predates the emptied Magento logs). Chromium 102 is still in the image, unused.
- `test_fork.py --copies 4 --image localhost/wa-shop-browser142:latest`: ALL PASSED (30/30), clone 23.3 s, 0 trap int3,
  0 segfaults. Copies need the relay restarted (`podman exec -d <copy> /opt/chr/bin/socat tcp-listen:9222,fork,reuseaddr
  tcp:127.0.0.1:9221`; no supervisord socket in copies): test_fork.py does it for any --image other than the 102 one.

### Replay of the recorded traces on tfork copies (2026-10-29)

- `wa_replay.py` (new): per task one source environment set up as in the recording (wa-shop-browser142, test_fork.py's
  flags incl. tmpfs /tmp), login + start URL in the source's Chromium, disconnect, `clone --live --copies=8` (tfork
  flags of test_fork.py), per copy HOSTS_FIX + CDP relay restart; each copy replays its rollout's actions (redo dir
  wins), sleeping the recorded model time (`--replay-latency 1`); page read / action / settle measured fresh; final
  reward via lite_eval. Per step: rows vs recorded (exact, count, acted-on row, a diff of up to 6 rows), URL after the
  action vs recorded. `--remap-ids 1`: when the row at the recorded id differs, act on the nearest row with the
  recorded (role, name).
- Memory (user: account inside the cgroups, not host MemAvailable, which drifts with evictable page cache): per env
  its cgroup memory.current + memory.stat anon / file / active_file / inactive_file / shmem / kernel / file_mapped,
  ws = current - inactive_file, memory.peak; sums over distinct cgroups; the common parent cgroup's own counters
  (`/libpod_parent`); PSS per env; host used kept for reference. Shared pages are charged to the cgroup that first
  touched them (the source), so per-copy cgroup numbers undercount: compare the parent / sum.
- `replay_report.py <run>` (new) summarizes.
- Pilot task 29 × 8 (`/mnt/data/btrfs/wa_replay/pilot29`, `pilot29b`): 8/8 replayed, 0 errors, rewards 8/8 equal to
  recorded; URL after each action 17/17 equal; rows identical only 10–12/25. The diffs are page variation, not 142:
  Magento's recommended-products block order is random, the cart badge ("My Cart" vs "My Cart 3 3 items") and the
  image gallery's buttons depend on JS load timing. Under 102 itself, same task + same URL across rollouts: 878/1,912
  identical. One acted-on id shifted (a missing cart-badge row) → `--remap-ids`.
- Pilot times: source setup 32 s, clone of 8 copies 31.2 s, fixup 2.9 s. Memory at peak (1 source + 8 copies, MiB):
  parent cgroup current 11,082 / ws 8,258 / anon 4,443 / file 5,701 (inactive 2,824) / shmem 1,986; source cgroup
  5,133 (ws 2,656), copy median 747 (ws 695); host used 15,758 (reference).
- Full replay, attempt 1 (`/mnt/data/btrfs/wa_replay/lite32_r3_tfork_aborted1`): wave 0 lost 3 of 4 groups, the clone
  failed with "crun tfork exited before 8 clones came up (got 2)"; podman reaped the failed bundles, so no CRIU logs.
  Stopped. wa_replay.py now clones with PODMAN_TFORK_NO_REAP=1, saves podman's stderr and the CRIU logs of a failed
  clone in `<run>/clone_fail/<src>_try<n>/`, removes partial copies and retries (`--clone-retries 2`); every failed
  attempt is a `clone_failed` event and replay_report.py counts them (and lists the 12 rollouts replayed from the redo
  traces).
- Attempt 2 (`..._aborted2`): t36 cloned, t37 and t31 failed. CRIU restorer: `Ring setup failed with -11` = io_setup
  EAGAIN, the host's native AIO limit: fs.aio-nr 51,792 of fs.aio-max-nr 65,536 with 12 environments up (~4,300 each,
  MySQL / InnoDB native AIO). Not io_uring (already disabled). Fix: `sysctl -w fs.aio-max-nr=1048576` (runtime; added to
  setup/after_reboot.sh). Stopped, relaunched as attempt 3.
- Mistake: kept bundles (NO_REAP) still had their copies' overlay mounts (rootfs-<i>) and a read-only btrfs subvolume
  (snap-ro) after the containers were removed; `rm -rf --one-file-system` skipped them. Cleaned by hand (umount,
  `btrfs subvolume delete`); wa_replay.py's drop_bundle() now does the same.
- Attempt 3 (`lite32_r3_tfork`, synchronous waves as recorded): stopped by the user after 4 of 8 waves (96 rollouts) to
  switch to osw_run.py's scheduling. Up to then: 16/16 clones first try (32–41 s), 0 errors, rewards 96/96 equal
  (24 vs 24), URL after action 750/757, 41 ids remapped (6 unmatched), action errors 46 = recorded 46. Working set per
  wave 30–34 GiB (tfork) vs 76–83 GiB (recording, fresh env per rollout); peak memory.current 44.6 vs 96.9 GiB; anon
  15–19 vs ~55 GiB. Source cgroup 5.1 GiB (ws 2.65), copy ws ~0.74 GiB. The parent cgroup (/libpod_parent) is larger
  than the sum over live envs (ws 44.6 vs 34.7 GiB): killed, not yet removed containers' page cache moves to the
  parent. Figures: ~/webarena_ws_waves_partial{.png,.svg,_detail.png} (`mem_timeline.py`, new: the OSWorld figure's
  style, one working-set line per system; `--detail` stacked cgroup split). Cleanup: `setup/cleanup_replay.sh` (new).
- wa_replay.py `--schedule groups` (new default, the user's ask: as osw_run.py, "as if running with the model"): every
  task group starts at t=0 (`--parallel 0`) and runs its own lifecycle (set up, fork, replay at the recorded model pace,
  score, kill its 9 environments as soon as its 8 rollouts end); clones 4 at once (`--clone-concurrency 4` =
  osw_run.py --fork-concurrency), setup unlimited (`--setup-concurrency 0`); `--mem-limit-gib 220` kills everything and
  exits when host used passes it (osw_run.py's mem_limit). Bundles found from the copies' io.podman.tfork.batch-id
  annotation (concurrent clones). fs.aio-max-nr raised to 4194304 (288 envs ≈ 1.24M AIO events).
- Groups run 1 (`lite32_r3_groups_aborted`, 04:03): clones 4 at once while ~28 sources set up (load avg up to 46):
  10 of 24 first clone attempts failed, all `tfork restore wait timed out after 10000ms` (the hard-coded
  `tfork_restore_wait_timeout_ms`, criu/cr-restore.c:238; OSWorld README saw the same). Not AIO (aio-nr 0.23M / 4.19M),
  not memory (73 GiB used). 11 groups finished, none lost yet when stopped (user: raise the timeout).
- CRIU: `tfork_restore_wait_timeout_ms` 10000 → 60000 (criu/cr-restore.c, uncommitted), `sudo make -j8` in criu/
  (criu/criu rebuilt 04:14). Clone times after this include up to 60 s of waiting where they used to fail.
- Mistake: cleanup left one container (`podman rm` lost a "database is locked" race with the kills' cleanup) whose name
  the relaunch reuses (same run dir name): removed by hand before the relaunch's clone of that group;
  cleanup_replay.sh now repeats rm until none is left.
- Groups run 2 (`lite32_r3_groups`) launched 04:19:39 with the 60 s timeout.
- Groups run 2 result (`/mnt/data/btrfs/wa_replay/lite32_r3_groups`, tfork, 60 s restore wait): 32/32 clones first try,
  0 failed attempts (clone 51 → 87 s as more sources were live); 32/32 groups, 256/256 rollouts, 0 errors; rewards
  254/256 equal. The 2 that changed are both task 103 (g0 1→0, g4 0→1, sum unchanged): a two-tab task whose steps are
  mostly `tab` switches with URL mismatches after them, likely tab order after the CDP reattach in a copy differs from
  the recording's (not verified; fix would map tabs by URL as ids are remapped). Epoch 12.8 min; peak working set
  101.0 GiB (79 live envs, ~3 min), peak memory.current 121.3 GiB; mem limit (220 GiB) never hit.
  Figures: ~/webarena_ws_groups.{png,svg} (tfork only, user's ask), ~/webarena_ws_groups_detail.png (with the
  recording's panel; not like for like: the recording ran in waves of 32 rollouts).
- wa_replay.py `--system criu` (new): osw_run.py's CKPT, per group 8 serial `clone --live --copies=1 --persistent=sync
  --tfork-tcp-close --tfork-ghost-limit=64M --tfork-full-memcopy` (full dump + restore, nothing shared with the source,
  no overlay rootfs), each copy counted live as it comes up; clones of up to 4 groups at once (each group's serial
  sequence holds a slot, as osw_run.py's FORK_SEM). Clone attempts now as osw_run.py: 5, backoff 20/40/60/80 s
  (`--clone-retries 4`). CRIU run: `lite32_r3_criu`, launched after the tfork run's cleanup.
- CRIU run (`/mnt/data/btrfs/wa_replay/lite32_r3_criu`, groups schedule, same as the tfork run otherwise): 32/32
  groups, 0 failed clone attempts, 0 group errors; per group 8 serial clones of ~25 s (200–215 s per group, vs tfork
  51–87 s for one 8-copy clone). 255/256 rollouts; 1 hung: `120__g1`, the copy's Chromium browser process spun in a
  syscall loop (main thread ~834 s system CPU vs ~187 s user, state R, CDP unresponsive) right after a CRIU restore;
  the replay has no per-step timeout so it waited 16 min; thread states + chromium.log saved in `hang_120_g1/`, then
  its Chromium killed by hand → TargetClosedError, reward unscored (recorded 1.0). Same rollout fine on tfork.
  Epoch: last normal group done 30.7 min (36.3 with the hang). Peak working set 157.4 GiB (67 envs, 6.8 min) vs tfork
  101.0 GiB; peak memory.current 180.0 vs 121.3; host used max 171.7 vs 116.1 GiB.
- CRIU's sawtooth: one rise per clone round (4 groups' slots move in lockstep, rounds end every 3.3–3.6 min); each
  group adds a ~2.25 GiB copy every ~25 s, the round's groups then free 9 envs each. Rises are new copies (574.8 GiB of
  ws added by copies appearing vs 11.4 GiB by existing copies growing); a copy grows only 0.19 GiB median over its
  rollout, the same on tfork (tfork copies start at 0.41 GiB). Downward trend: the 32 sources set up at t=0 and wait
  for a clone slot (68–83 GiB before any copy).
- Figures: ~/webarena_ws_tfork_criu.{png,svg}, ~/webarena_ws_tfork_criu_detail.png.
- Leftovers: the run's final `podman rm` reported 288 removed; cleanup_replay.sh found 0 left this time.
- To do in wa_replay.py: per-step timeout (a hung browser should fail its rollout, not stall the run); repeat the final
  rm until none is left; map `tab` actions by URL (task 103's two changed rewards on tfork).

### AgentENV (AENV) for WebArena (2026-10-29)

- User decisions: apply osworld_rl's setup-host.sh as in SETUP.md (persistent: ublk_drv at boot, /etc/sysctl.d/99-aenv.conf
  pid_max / conntrack / neigh), state + registry + template on /mnt/data/btrfs, CLI from the release install script.
- `setup/aenv/install.sh` (new): setup-host.sh + the CLI (install-cli.sh downloaded to /mnt/data/btrfs/aenv/dl_cli and
  read first; it checks the release tarball's SHA256) → ~/.local/bin/aenv 0.2.4 (OSWorld used 0.2.3).
- `setup/aenv/start-server.sh` (new): osworld_rl's with state /mnt/data/btrfs/aenv/env (AENV_HOME_PATH=/workspace/env in
  the server image), this folder's config.toml (osworld_rl's, image.cache capacity_gb 100 → 160: docker reports the
  image as 111 GB), kernel.io_uring_disabled=0 (runtime; tfork / CRIU need 2 again). aenv-server latest (image
  ea9bffa35e17), health 204. `fork-smoke.sh` (copy): alpine fork of 2 in 0.18 s, in-memory counter alive in both copies.
- `setup/aenv/make_template.sh` (new): registry:2 on /mnt/data/btrfs/aenv/registry (127.0.0.1 / 172.17.0.1 :5005), push
  wa-shop-browser142 (one 65.8 GB layer), `aenv pull` → template `wa-shop142`, 4 vCPU / 8 GiB, start command = the
  runtime dirs /docker-entrypoint.sh makes + supervisord (not the entrypoint: it re-inits MySQL when /run/mysqld/.init
  is missing), ready = MySQL + Chromium DevTools answer. So the template snapshot has the site running.
- Memory: every Firecracker process is in aenv-server's docker cgroup (no per-VM cgroup); guest RAM shows as the VMM's
  file-backed (snapshot) + anon pages. Plotted: the aenv-server cgroup's ws minus its idle baseline (run_start
  `aenv_baseline`); per VM: VMM smaps PSS split. The OSWorld figure's script is not in this checkout.
- `aenv_env.py` (new): osw_run.py's Aenv (Forwarder into aenv-server's netns, VMM discovery, fork API, pairing); pairing
  reads the tag from socat on :5000 in each copy (the WebArena image has no OSWorld server). wa_replay.py `--system
  aenv`: source = `aenv start wa-shop142` + the same setup steps via `aenv exec`; copies = fork API, no fixup (the VM's
  processes, CDP relay included, survive the VM fork); teardown = `aenv rm` at group end.
- wa_replay.py also: `--step-timeout 120` (page read / action; scoring 5x): a hung browser fails its rollout; the final
  podman rm repeats until none is left.
- Template build attempt 1 (registry at 172.17.0.1:5005, as OSWorld): `regctl registry set` hung: the host firewall
  (nftables input policy drop) blocks container -> host, so aenv-server cannot reach 172.17.0.1. Fix without touching
  the firewall: docker network `aenv-net` with aenv-registry and aenv-server, image ref aenv-registry:5000/... ; regctl
  is not on the server image's PATH (/workspace/env/deps/regctl/v0.11.5/regctl). make_template.sh does both.
- Template build attempts 2–3: the conversion's scratch (image-cache/staging/<tmp>/layer-0/upper.data) grew past 194 GB
  (stopped by hand at 112 GB free) and past 226 GB (with setup/aenv/disk_guard.sh, new: stops aenv-server below 50 GB
  free). Removing podman's wa-shop-orig-browser freed little at first (shares its base layer with wa-shop-browser142),
  later btrfs showed 324 GB free. AENV converts every OCI layer into a filesystem of a fixed virtual size
  (`LAYER_VIRTUAL_SIZE_GIB = 64`, AgentENV src/image/oci_image.rs:63); this image's one big layer is ~111 GB
  uncompressed (docker's figure; the podman store shows 62 GB, btrfs compression likely), so it likely cannot fit, and
  the log-structured upper keeps growing as blocks are rewritten (my reading, not verified). A stopped build leaves
  its template holding the name; make_template.sh now deletes an unfinished wa-shop142 first.
- Found 06:23: 18 tfork copies from the stopped groups run 1 (started 04:12:23–29, the clones in flight when I stopped
  the unit) still running in /libpod_parent/libpod-<id> cgroups that podman no longer knows (it rolled back their
  registration), ~0.8 GiB each, ~15 GiB in all, through the tfork groups run 2 and the whole CRIU run. Plotted working
  sets sum only each run's own env cgroups, so they are unaffected; host used (reference) and the /libpod_parent
  numbers include ~15 GiB of them, the 220 GiB guard had that much less headroom, and they added some (mostly idle)
  CPU load. Killing them (cgroup.kill) was refused by the permission check: left for the user.
- Template build attempt 4 (disk_guard at 50 GB): stopped by the guard at 06:25:10 (40 GB free; converted layer
  upper.data 226 GB and growing). AENV's staging is deleted on stop; btrfs gave the space back within a minute (290 GB).
- User: patch the 64 GiB limit and build the server. `setup/aenv/build_server.sh` (new): fresh clone of upstream tag
  v0.2.4 (9f62cbe, the release of the 0.2.4 CLI; ~/Repos/AgentENV is from 2026-07-28 with untracked work, untouched)
  in /mnt/data/ssd4/yutong/aenv_build/, `agentenv-v0.2.4-user-vsize256.patch` (new), CARGO_BUILD_JOBS=8, docker build
  → aenv-server:v0.2.4-uservsize256. The patch: v0.2.4 asserts LAYER_VIRTUAL_SIZE_GIB == 64 at compile time for AENV's
  tools image (resolver.rs:188, a v1 release contract), so the constant stays and a new `layer_virtual_size_gib
  (converter_id)` gives 256 GiB to user images and 64 to the `tools-oci-rootfs-v1` converter, at the 3 uses (pull
  converter, BuildKit content converter, conversion cache key). Converted layers are hard-linked into the cache
  (commit_index.rs seed_commit_file_trusted_descriptor), not copied: peak ≈ downloaded layers (~42 GB) + converted
  layer (~111+ GB).
- start-server.sh: `AENV_SERVER_IMAGE` (default upstream latest), joins aenv-net.
- Sparse patch (user's pick, with the registry moved to /mnt/data/ssd4/yutong/aenv_registry, copy diff-checked, btrfs
  copy deleted): `agentenv-v0.2.4-sparse-convert.patch` (new) adds `-s` to overlaybd-create in the conversion (its only
  caller); build_server.sh applies both patches → aenv-server:v0.2.4-uservsize256-sparse (3 min, cached).
  `setup/aenv/test_sparse_convert.sh` (new): alpine 3.22 converted fresh (9 s), root device 252 GB, file visible in a
  fork: OK. WebArena template `wa-shop142` ready in 38 min: overlaybd-apply is single-threaded and CPU-bound (100% of
  one core, disk idle); the sparse layer stayed at the data size; the committed layer is 63 GB (the podman store's
  62 GB: docker's 111 GB was an overcount); peak btrfs use ~115 GB. Launcher bug: its readiness check grepped one
  line of multi-line JSON, so it first refused a ready template; fixed (parses the JSON).
- AENV run (`/mnt/data/btrfs/wa_replay/lite32_r3_aenv`, groups schedule, all 32 at t=0): 32/32 groups, 0 failed forks,
  0 group errors; source VM setup 72–149 s; fork per group median 41.8 s, of which AENV's fork API 11.4 s (one fork at
  a time: aenv_env.py's lock, as osw_run.py, serializes starts and forks to pair VMMs), pairing 1–31 s. 256 rollouts,
  0 errors, 2 unscored (scorer page load timed out), 18 rewards changed (tfork 2, CRIU 5). Epoch 11.8 min.
  Peak working set 177.1 GiB (aenv-server cgroup minus its 0.3 GiB idle baseline; 157 VMs, 6.9 min); memory.current
  197.4 GiB; host used max 175.1 GiB (incl. ~15 GiB of the leaked tfork copies); 220 GiB limit not hit.
- Why AENV's rewards drift: CPU saturation. ~160 VMs (4 vCPU each) on 64 cores: load average 375, 98% CPU busy (53%
  system), Firecracker ~41 cores; each VM runs its own guest kernel + Elasticsearch / MySQL / Chromium. Page actions
  median 9.36 s (p90 16.3) vs tfork 0.90 (7.0) / CRIU 0.80 (4.8); action timeouts 555 vs 56 / 42. Task 72's flips
  (0→1): the recording's last click went to order history; in the replay that click hit Playwright's 5 s timeout and
  the page stayed on order 189, which is what url_match checks. Copy memory: no per-VM cgroup, so per-copy cost is not
  split out; the residual ~13 GiB at the end is likely AENV's warm VM pool (64 Firecracker processes stay up).
- Summary (same schedule, same image, same traces):
  | | tfork | CRIU | AENV |
  |---|---|---|---|
  | peak working set | 101.0 GiB (64 envs) | 157.4 GiB (67) | 177.1 GiB (157) |
  | epoch | 12.8 min | 36.3 (30.7 without the hang) | 11.8 |
  | fork per 8-copy group (median) | 67.6 s | 204.7 s | 41.8 s (API 11.4) |
  | rewards changed / 256 | 2 | 5 | 18 |
  Figure: ~/webarena_ws_3sys.{png,svg}. Logs: ~/webarena_logs/ (AENV run and template logs added).
- Capped AENV run (user: like CRIU, ~64 live envs → `--parallel 7` = 63 envs): first try stopped by the user at
  start (`lite32_r3_aenv_p7_aborted`); it left 55 sandboxes (the runner does not clean up on SIGTERM), removed with
  `aenv rm`. User: stop the VMs completely first → setup/aenv/config.toml `[pool.firecracker] enabled = false,
  startup_prewarm = false` (the warm pool kept 64 idle Firecracker processes, ~3.4 GiB in the aenv-server cgroup,
  inside AENV's measured memory and in its baseline; the first AENV run's ~13 GiB end residual is likely the pool).
  Server restarted (patched sparse image): 0 Firecracker processes, cgroup 0.03 GiB; fork-smoke OK without the pool
  (2 copies 0.18 s). Relaunched 08:01:39 → `lite32_r3_aenv_p7`. VM starts and forks now spawn Firecracker on demand,
  so they may be slower than in the first AENV run (which had the pool).
- Capped run 2 (`lite32_r3_aenv_p7_stopped`, pool off): stopped by the user after 134 rollouts (0 errors, rewards all
  equal; actions median ~1.5 s, p90 ~6 s; peak ws 64.1 GiB at 55 VMs; fork per group ~9–11 s, API ~3 s); its 31
  sandboxes removed. User: same as tfork → same schedule (all 32 groups at once, `--parallel 0`), pool off:
  `lite32_r3_aenv_nopool`, launched 08:07:48 from 0 sandboxes / 0 Firecracker processes.
- Most live envs at once per run: recording 32, tfork waves 36, tfork groups 79, CRIU 72, AENV (pool on) 171,
  AENV capped 63.
- AENV run, tfork's schedule with the pool off (`lite32_r3_aenv_nopool`): 32/32 groups, 0 failed forks, 0 group
  errors; 256 rollouts, 0 errors, 4 unscored, 9 rewards changed; epoch 11.1 min; fork per group median 50.1 s; peak
  working set 175.5 GiB (140 VMs; 156 at most); actions median 8.54 s, p90 14.56 s, 615 timeouts: CPU saturation
  again. Final numbers of the first AENV run (pool on; my mid-run figures were partial): actions median 7.52 s, p90
  15.16 s, 633 timeouts.
  | | tfork | CRIU | AENV pool on | AENV pool off |
  |---|---|---|---|---|
  | peak working set | 101.0 GiB (64 envs) | 157.4 (67) | 177.1 (157) | 175.5 (140) |
  | most live envs | 79 | 72 | 171 | 156 |
  | epoch | 12.8 min | 36.3 (30.7 w/o hang) | 11.8 | 11.1 |
  | fork per 8-copy group (median) | 67.6 s | 204.7 s | 41.8 s | 50.1 s |
  | page action median / p90 | 0.90 / 7.0 s | 0.80 / 4.8 | 7.52 / 15.2 | 8.54 / 14.6 |
  | rewards changed / 256 | 2 | 5 | 18 | 9 |
  Figure: ~/webarena_ws_3sys_nopool.{png,svg} (tfork, CRIU, AENV pool off). mem_timeline.py: legend only by default
  (peak labels landed on other lines), `--direct-labels` to add them.
- User: cap AENV near 120 GiB → (instead of a memory-based admission, which I had started to design: a group starts
  only while live ws + ~11 GiB reservations of not-yet-forked groups stay under the cap) "start 2/3 at the beginning
  and the rest afterwards": `--parallel 21` (21 groups at t=0, each of the other 11 starts when a group ends), pool off:
  `lite32_r3_aenv_p21`, launched 08:22:29. Expectation: the uncapped runs never had more than 17–19 groups live at
  once (forks are serialized, early groups end before late ones fork), so this saves mostly the ~11 idle sources
  (~2.2 GiB each) of the uncapped start; peak likely ~150 GiB, not 120.
- `lite32_r3_aenv_p21_stopped` (2/3 at start): stopped by the user near the end (253/256 rollouts, 0 errors, rewards
  all equal at the last check); peak working set 151.7 GiB (124 VMs; 132 max); actions median 7.11 s, p90 12.1 s,
  load average up to ~233: still CPU-saturated. User: `--parallel 16` (16 groups = 144 envs max) → `lite32_r3_aenv_p16`.
- `lite32_r3_aenv_p16` (`--parallel 16`, pool off): 32/32 groups, 0 failed forks, 0 group errors; 256 rollouts, 0
  errors, 0 unscored, 0 rewards changed; epoch 9.6 min; peak working set 123.1 GiB (104 VMs, 3.4 min; 104 max);
  host used max 129.9 GiB; fork per group median 15.9 s (API 5.9 s); actions median 2.23 s, p90 10.0 s, 358 timeouts
  of 2246 steps (load average ~120–195 at its peak). Figure: ~/webarena_ws_3sys_p16.{png,svg} (tfork and CRIU
  uncapped, AENV at 16 groups: not the same schedule).
- User: rerun tfork and CRIU with `--parallel 16` (same schedule as the 16-group AENV run). Host back to podman mode:
  aenv-server stopped (0 sandboxes), kernel.io_uring_disabled=2; 0 containers / bundles / tfork mounts. The 18 leaked
  tfork copies from 04:12 were no longer running at this point (0 libpod cgroups with processes; not killed by me,
  cause not known), so they don't affect these reruns. Runs one after the other: `lite32_r3_tfork_p16`, then
  `lite32_r3_criu_p16`, each followed by cleanup_replay.sh (driver: scratchpad run_p16_pair.sh, log
  /mnt/data/btrfs/wa_replay/p16_pair.log).
- Action timeouts (explained to the user): the agent executor's own Playwright limits (wa_run.py: click / fill /
  select 5 s, goto / go_back / Enter 30 s), as recorded. Counts over 2254 steps: recording 34, tfork 56, AENV uncapped
  615 (551 clicks at 5 s, 35 Enter at 30 s), AENV 16 groups 366; the 120 s step guard never fired. User: make it 60 s
  for all → wa_replay.py `--action-timeout` (new; 0 = the recorded limits, unchanged): one limit for every action;
  with it set the step guard becomes max(step-timeout, 2 x action + 30). The running tfork p16 rerun and the CRIU p16
  rerun after it use the default (it was loaded / is not passed), so the pair stays consistent.
- User: only AgentENV at 60 s, all groups at the start, after the tfork p16 rerun. Queue (driver: scratchpad
  run_queue.sh / run_queue.log; the earlier pair driver stopped before it started CRIU): tfork p16 (running, recorded
  limits) → cleanup → start-server.sh (patched sparse image, pool off, io_uring 0) → `lite32_r3_aenv_t60` (`--system
  aenv --parallel 0 --action-timeout 60`) → leftover sandboxes removed → aenv-server stopped, io_uring 2 →
  `lite32_r3_criu_p16` (recorded limits, as the earlier request) → cleanup.
- User: stop everything, run only AgentENV with the 60 s limit. Queue driver stopped; tfork p16 stopped at 253/256
  rollouts → `lite32_r3_tfork_p16_stopped` (peak ws 79.6 GiB at 80 envs; actions median 1.01 s; 0 failed clones).
  2 copies of task 103 (g0, g2) crashed: `Page.evaluate: Target crashed` (renderer), nothing in dmesg; their
  crashpad minidumps + chromium.log saved in `lite32_r3_tfork_p16_stopped/crash_103/` (not analysed). Task 103 is the
  two-tab task; not seen in the earlier tfork runs.
- Cleanup of a stopped tfork run is slow: the runner defers `podman rm` of finished groups to the end of the run, so
  cleanup_replay.sh removed up to ~288 containers + 32 bundles / 156 mounts (≈7 min, 09:00–09:07). Waited for it
  before switching io_uring to 0 (podman-tfork's preflight would refuse the remaining podman calls).
- `lite32_r3_aenv_t60` launched 09:08:13: `--system aenv --parallel 0 --action-timeout 60`, pool off, patched sparse
  server, io_uring 0, 0 sandboxes / 0 Firecracker processes before.
- `lite32_r3_aenv_t60` (all 32 groups at once, pool off, `--action-timeout 60`): 32/32 groups, 0 failed forks, 0 group
  errors; 256 rollouts, 0 errors, 1 unscored, 3 rewards changed (5 s run: 9; tfork: 2); action errors 102 (timeouts 35)
  vs 683 (615) at 5 s and 92 recorded; URL after action same 1882/2099 (5 s: 1516; tfork: 1954). Cost: epoch 22.6 min
  (5 s: 11.1), rollout median 135.4 s (105.6), actions median 8.68 s, p90 28.9 s, max 130 s (fill + Enter); memory the
  same (peak ws 176.7 GiB at 145 VMs, 171 max): the CPU is still saturated, actions now wait instead of failing.
  Figure: ~/webarena_ws_3sys_t60.{png,svg} (tfork and CRIU uncapped at the recorded limits; AENV at 60 s).
- User: retry 16 groups with AgentENV at 60 s. `lite32_r3_aenv_p16_t60` launched 11:19:53 (scratchpad
  launch_aenv_p16_t60.sh): `--system aenv --schedule groups --parallel 16 --rollouts 8 --action-timeout 60`, pool off,
  patched sparse server, io_uring 0, 0 sandboxes / 0 Firecracker processes before. Same schedule as
  `lite32_r3_aenv_p16` (5 s limits): the pair isolates the limit.
- `lite32_r3_aenv_p16_t60` (16 groups, pool off, `--action-timeout 60`), done 11:46:36; numbers from cmp_runs.py (new:
  epoch, peak ws, fork, actions = t_act_end - t_act_start, last groups, slowest steps; same measure for every run):
  32/32 groups, 0 failed forks; 256 rollouts, 0 errors, 0 unscored, 1 reward changed (5 s p16: 0); action errors 103
  (timeouts 36) vs 436 (366) at 5 s; URL after action same 1914/2099 (5 s p16: 1735). Peak ws 128.0 GiB (104 VMs,
  3.7 min; 104 max; 5 s p16: 123.1). Epoch 26.5 min (5 s p16: 9.6): every group but task 118's was done by 10.3 min;
  118's (started 4.8 min) ended at 26.5. Its copies g0 / g2 / g6 had 4 / 10 / 6 selects that time out at 2 x 60 s
  (label, then value) = 481 / 1081 / 721 s; every one of them failed in the recording too. Over the run: actions that
  failed in the recording took 2974 s (86 actions) at 60 s vs 384 s (91) at 5 s; actions the recording did not fail
  that failed now: 17 (433 s) vs 345 (3000 s). Figure ~/webarena_ws_3sys_p16_t60.{png,svg} (tfork / CRIU uncapped at
  the recorded limits; AENV 16 groups at 60 s): AENV's flat ~17 GiB tail 10.3–26.5 min is task 118's group (9 VMs).
  Run copied to ~/webarena_logs/wa_replay/.
- mem_timeline.py `--csv <path>` (new): writes the plotted series (system, run, minutes, working_set_gib, live_envs).
  ~/webarena_ws_3sys_t60.csv: from lite32_r3_groups=tfork lite32_r3_criu=criu lite32_r3_aenv_t60=aenv (555 rows); the
  PNG redrawn with it is byte-identical to ~/webarena_ws_3sys_t60.png.
- User: a version without the flat tails, each line drawn down to 0 where it flattens, plus a CSV for Excel.
  mem_timeline.py `--cut <system>=<min>` (new: line ends at its last sample at or before <min>, then drops to 0) and
  `--csv` now spreadsheet-shaped (per system a time (min) and a working set (GiB) column; row i = sample i). Cut at
  the first sample with only the last group left: tfork 12.723 (its last sample), AgentENV 12.814 (task 118 left),
  CRIU 30.737 (task 120 left). ~/webarena_ws_3sys_t60_cut.{png,svg,csv} (--cut tfork=12.73 --cut aenv=12.82 --cut
  criu=30.74) and ~/webarena_ws_3sys_t60_cut.xlsx from ws_xlsx.py (new; openpyxl venv
  /mnt/data/ssd1/yutong_data/venv-xlsx): sheets data / figure (native scatter chart) / notes (runs, cut points).
  ~/webarena_ws_3sys_t60.csv rewritten in the same shape (uncut; its PNG still byte-identical).
- 17:4x: os4agent `webarena-memory-sweep` and local `osworld-memory-sweep` fast-forwarded (user) to origin's fc24fb0bb
  (agents/osworld_rl only: --release-copies, --obs-timeout, AENV slow-VM waits, /proc/stat guest double count, Gate,
  spec_exec.py / --spec-exec / --prefix-cache (untested), timeline_plot.py, epoch_status.py, thread_states.py).
  wa_replay.py: no CPU sampling (the /proc/stat bug is not here), already `rm -f -t 0`, frees copies per group.
- CORRECTION to the 08:44 entry ("leaked tfork copies no longer running"): they are still running. 18 complete shop
  stacks (mysqld, nginx, php-fpm, redis, java, chromium, socat, ...; 180 nginx + 144 chromium processes) in 18
  /libpod_parent/libpod-* cgroups, memory.current 19 GiB in all; podman ps shows 0 containers, 0 tfork bundles and 0
  tfork mounts are left (cleanup removed them; the processes run on the lazily unmounted rootfs). Started 04:12:23-29,
  during lite32_r3_groups_aborted: 4 sources (hostnames cda587bcbb1a 5, d0f277cb02b1 5, 179899b72d24 4, d8db298f9b47 4)
  = 4 clones in progress, 4-5 of 8 copies each, never registered with podman. So they were up, idle, through every
  measured run from lite32_r3_groups (04:19) on: not in any run's working set (per-env cgroups / aenv-server cgroup),
  but in host used (~+19 GiB) and in the /libpod_parent parent cgroup sample. Not killed yet (asked the user).
- User: kill them. setup/kill_orphan_stacks.sh (new): kills /libpod_parent/libpod-* cgroups that podman does not know
  and that hold only shop-image processes, then removes the emptied cgroups (DRY=1 lists). Its podman lookup needs
  PODMAN_TFORK_SKIP_SYSCTL=1 while io_uring is 0 (podman-tfork.sh refuses otherwise; caught in the dry run). 17:46:56:
  18 stacks killed (all with the 4 hostnames above, 31-32 processes each), 0 libpod cgroups with processes left;
  host used 30 -> 9 GiB, /libpod_parent 0 GiB. 19 older empty libpod-* cgroup dirs remain (harmless).
