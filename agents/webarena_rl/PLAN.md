# WebArena GRPO on forked environments: memory over time (plan)

Counterpart of `agents/osworld_rl/` for WebArena shopping. Question: how much host memory do GRPO rollouts use over
time when each task's environment is set up once and forked into N copies, with tfork, CRIU and AENV? Memory is
sampled every 5 s for the whole run, not only at the peak.

Host: wuklab-08 (2× A6000, 64 cores, 499 GB RAM, kernel 7.0.0-34-generic, btrfs disk at `/mnt/data/btrfs`). Model:
Qwen3-VL-8B-Instruct on a RunPod GPU through an ssh tunnel. The memory runs replay a recording, so they need no GPU.

## Benchmark: original WebArena image, WebArena-Lite shopping tasks

- **Site:** the original WebArena shopping image `shopping_final_0712` (Magento on Alpine: nginx, PHP-FPM, MySQL,
  Elasticsearch, Redis under supervisord). The RL papers that train on WebArena (WebRL, WebAgent-R1) use the original
  images. Already imported on this host (`docker images`: `shopping_final_0712:latest`). Provenance caveat: the CMU
  and archive.org downloads are gone; this copy is the unofficial HF repackaging `Atesting1/webarena-env`
  (`shopping_rootfs.tar.gz`, flattened to one layer; SHA-256 matched HF's record, not an official digest). Imported by
  `poc-trajectories/webarena/06_original_shopping.py load-hf` (step 133 there).
- **Tasks:** WebArena-Lite (THUDM VisualAgentBench @9055fc2, `VAB-WebArena-Lite/new/test_webarena_lite.raw.json`):
  165 human-checked tasks, 45 of them shopping. These 45 are the task pool. Start with a few long ones for smokes.
- **Scoring:** WebArena-Lite's evaluator (string match / URL match / program-based state checks, as in WebArena's
  `evaluation_harness`, with Lite's fixed answers), ported into this folder. Not WebArena-Verified's HAR scorer.
- **Site setup** (what WebArena-Lite's `refresh_website_dockers.sh` does), done once per task group in the source
  environment: set Magento's base URL, flush the cache, log in as the customer through the login form (the original
  image has no auto-login header). Measured on this host: ~45 s per site; idle 8.64 GB (anon 1.59, file 6.81 GB),
  Elasticsearch 1.33 GB PSS, 6.8 GB written at container start.
- WebArena-Verified (ServiceNow, 2025; slim images, HAR scorer; the teammate's WebArena GRPO loop used it) stays out
  of the main comparison; it can be a footnote run later.

## Design

- **What is forked (decision 10-28: option B):** one container holding the whole environment: the shopping site
  plus a headless Chromium with its DevTools port 9222. Image `wa-shop-orig-browser` (`image/`), built
  `FROM shopping_final_0712` with Alpine's `chromium` package (Chromium 102; Playwright's own Chromium needs glibc)
  as one more supervisord program. The site's base URL is `http://localhost` inside the container, so every copy
  works without rewriting it. Why B and not "site only, a fresh browser per rollout on the host" (option A, how the
  RL papers run WebArena):
  - forking mid-rollout (speculation, beam lookahead, branching from a shared prefix) needs the browser's state:
    typed but unsubmitted fields, scroll, tabs, history, page JavaScript state. None of it is in the site's database;
  - tfork, CRIU and AENV (a whole VM) all fork the same thing, and the WebArena numbers stay comparable with the
    OSWorld ones, whose desktop includes Chrome;
  - after a fork the browser's ~0.5 GB can be shared; with A each rollout pays it in full;
  - B still gives A's number: the sampler splits each container's processes into site and Chromium.
  At task start A would lose little (a login cookie and the start page, rebuilt in 1–2 s); the case for B is the
  mid-rollout fork. Step 1a decides: if Playwright cannot drive Chromium 102 over CDP, fall back to A.
- **Task setup in the source:** start the container, wait for MySQL and the site, base URL + cache flush, log in, open
  the task's start URL in the browser, let it settle.
- **After the fork, per copy:** attach Playwright over CDP to the copy's Chromium, take the page left at the start
  URL, run the agent, score with the Lite evaluator (it reads the final page / answer and, for state tasks, the
  copy's own database).
- **Agent:** the text agent of the teammate's WebArena GRPO loop (`wa_agent.py`: element rows `[id] role "name"`,
  one JSON action per step), unchanged except for the login handling.
- **Runner:** `wa_fork_run.py`, reusing `agents/osworld_rl/osw_run.py`'s pieces (memory sampler, podman/tfork/CRIU
  fork with retries, AENV fork, sync gates, `events.jsonl` / `mem.jsonl` layout), so `analyze.py` and the plots
  work for both benchmarks.
- **Memory:** per environment PSS (anon / file / shmem), RSS and the cgroup's memory.current / memory.stat, plus host
  used memory and each group's phase, every `--sample-s 5` seconds.

## Steps

1. **Environment image and a no-fork baseline** (`--system reset`: one fresh container per rollout, under docker).
   Tests everything WebArena-specific before tfork exists here.
   - 1a. Build `wa-shop-orig-browser` (`image/Dockerfile`): Chromium from Alpine, a supervisord program for it; check
     the site and CDP answer, and that Playwright (`connect_over_cdp`) can drive Chromium 102 through the site setup
     (base URL, cache flush), a form login and a few clicks and page reads (`test_image.py`). Pass → option B;
     fail → option A. **Done 10-28: passed → option B.** Needs Playwright 1.44.0 (1.64 calls `checkVisibility`,
     missing in Chromium 102); details in NOTES.md.
   - 1b. Port the WebArena-Lite task file and evaluator; check them on recorded rollouts from step 133. **Done 10-28**
     (`lite_eval.py`, `test_lite_eval.py`). Open: the fuzzy_match judge for 10 tasks (default: the served policy
     model; the original used GPT-4-1106-preview).
   - 1c. `wa_fork_run.py --system reset` smoke: 1 task × 2 rollouts with the local Qwen3-VL-8B (no RunPod yet).
2. **tfork on this host:** build os4agent in this checkout (submodules, `criu/`, `crun/`, `conmon/`, `podman/`
   `build.sh`, which also loads the kernel modules), apply `agents/osworld_rl/setup/podman-tfork-cgroup-path.patch`,
   podman storage on `/mnt/data/btrfs/podman`, the sysctls of `agents/osworld_rl/SETUP.md` steps 1–2, a host copy of
   `containers-os4agent.conf`. Check with os4agent's wiring checks and a small alpine clone. **Done 10-28**
   (`setup/build_tfork.sh`; alpine live clone of 2 copies in 1.3 s, state carried over; the cgroup-path patch is not
   applied yet, it is only needed for a clone of a clone). Step 1c deferred: tfork first (user decision).
3. **Fork the WebArena environment:** load `wa-shop-orig-browser` into the btrfs podman store; `--system tfork` and
   `--system criu` smokes (1 task × 2 copies). Risks to check: tfork closes established TCP at the fork (the CDP
   websocket; PHP ↔ MySQL / Elasticsearch / Redis); `/etc/hosts` refill; copies get different IPs; the 6.8 GB the
   original image writes at start.
4. **Recording with the live model:** RunPod pod (A100 SXM 80GB, $1.79/hr secure at the 10-28 read; created only for
   this step, with this host's ssh key, and stopped after), `pod_serve.sh` (Qwen3-VL-8B as `qwen3vl8b`), ssh tunnel to
   :8100. Record the WebArena-Lite shopping tasks on tfork (all 45, or the subset decided after the smokes).
5. **Memory over time:** replay the recording on tfork and CRIU with `--replay-latency 1` (the recorded model pace,
   so the time axis is real) and `--sample-s 5`; `mem_timeline.py` plots memory against time per system, phases
   shaded, working set and PSS.
6. **AENV:** template from `wa-shop-orig-browser` (large: the original image is ~63 GB unpacked), then the same
   replay.
7. **Scale:** the same at several numbers of concurrent groups, as `scale_mem.sh`, keeping the full time series.

## Log

Each step's commands, results and mistakes go in `NOTES.md` in this folder.
