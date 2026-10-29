# OSWorld on wuklab-08: setup and runs (log)

Goal (user, 2026-10-29): GRPO on OSWorld, 16 non-web tasks x 8 rollouts, 10 epochs, with spec execution
(`--spec-exec`) and the prefix cache (`--prefix-cache`): (1) the reward curve, to show both leave RL reward unchanged
(per-epoch paired check: replay each epoch's actions with the feature off, compare rewards and observations);
(2) the hit rate of each. Time saved is out of scope (a teammate is on it). Model + trainer on a RunPod pod.

## Setup (2026-10-29)
- os4agent `webarena-memory-sweep` at fc24fb0bb. `podman-tfork.sh`: setup/podman-tfork-cgroup-path.patch applied
  (user OK; clone of a clone, which spec execution needs). Uncommitted.
- `containers-os4agent.conf` here: /mnt/ssd2/os4agent -> this checkout (SETUP.md: edit it on another host).
  Uncommitted, host-specific: don't commit.
- On btrfs, linked from here: `OSWorld/` (xlang-ai/OSWorld at 1a572e62, `setup/patch_chrome_a11y.py`: 88 chrome
  launches patched), `venv/` (uv, py3.11, setup/requirements-06.txt; 6.9 GB; UV_CACHE_DIR / python on btrfs),
  `traces/`, `pod_backup/` -> /mnt/data/btrfs/osworld/. The root disk has 46 GB free (under the 50 GB floor).
- Image `ghcr.io/wuklab/webtop:ubuntu-kde-osworld`: setup/build_kde_osworld_on_published.sh (new), a thin layer on
  the published `ghcr.io/wuklab/webtop:ubuntu-kde` (9.14 GB, 2 months old) with the 11 files
  setup/ubuntu-img-kde-osworld.patch adds / changes (applied to ubuntu-img at fb313e8dd) + its apt packages / env /
  /home/user link. Checked: the base's pyautogui.py shim, wrapped-chromium, wrapped-code equal fb313e8dd's, and its
  code.desktop is already wrapped. The LibreOffice registry dir is a symlink to /etc/libreoffice/registry in the base,
  so the no-recovery .xcd goes there. Copied into the btrfs podman store.
- Tasks: grpo_batch16_noweb.json (gimp 4, calc 4, impress 3, writer 3, vlc 2) from grpo_batch32v2.json without
  chrome, vlc bba3381f (streams a URL inside the desktop) and calc 4e6fcf72 (evaluator names a URL); task setup
  downloads run on the host, so no container internet is needed. smoke_noweb2.json: calc 42e0a640, gimp 7a4deb26.
- Pod (RunPod MCP): `whcbv4x3ak63un` "osworld-smoke", A100-SXM4-80GB secure, $1.79/h (availability LOW in US-MD-1 /
  US-WA-1 at create), runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404, 200 GB container disk, no volume, 22/tcp,
  ssh key ~/.ssh/runpod_wa (new). ssh root@185.216.23.121 -p 10091 (changes on restart). pod_serve.sh with
  GPU_UTIL=0.4 (trainer shares the GPU), LoRA on.
- smoke_wuklab08.sh (new): stages tunnel / live / spec / prefix / loop.

## Smoke test, part 1 (2026-10-29)
- `traces/smoke_live` (live, both features off, tfork, 2 tasks x 2 rollouts, 18:19-18:31): 4 rollouts, 52 steps, 0
  errors, reward 0 for all 4. Per step: boot 24 s, task setup 7-24 s, fork 3.5 s; env time per step 3-18 s (gimp)
  and 19-35 s (calc: the a11y tree of a sheet).
- `traces/smoke_prefix1` (replay with --prefix-cache, depth 2): every save failed: osw_run.py's Podman.save() is
  `podman container checkpoint`, which does not handle tfork clones ("template configuration at
  .../libpod/containers/<copy>/userdata/config.json not found"). User: stopped the run (cleaned: 0 containers /
  bundles / mounts); don't use podman checkpoint -- docs/TFORK_RESTORE.md (origin/main 723818076 "fix snapshot
  restore"): persistent live clone + `podman container tfork-restore`.
- User: rebase onto main + origin/osworld-memory-sweep. Dropped the uncommitted cr-restore.c timeout edit (main has
  the same 60 s + CRIU_TFORK_RESTORE_WAIT_MS); all uncommitted tracked diffs saved first to
  /mnt/data/btrfs/osworld/pre-rebase-20261029-1836.patch. `git rebase --autostash origin/main`: clean; branch =
  723818076 + the two osworld commits (range-diff: identical; now 9b449b829, 1246712d1); differs from
  origin/osworld-memory-sweep only in main's 21 files. Not pushed (no upstream).
- setup/rebuild_tfork_stack.sh (new): make -j8 of criu (+lib), crun, podman (no apt / module reload; main's change
  does not touch the modules). 18:37: podman has `container tfork-restore`, `clone --persistent`.
- test_tfork_restore.py (new): calc task desktop -> rollout copy -> action A -> save = `clone --live
  --persistent=async --copies=1` of the copy, wait DumpStatus done, stop it -> action B -> `tfork-restore`.
  - copy made with --tfork-overlay-btrfs (osw_run default --overlay-rootfs 1): save fails 5/5 ("Not a Btrfs
    filesystem": the copy's rootfs is an overlay mount; an overlay clone of it is the recursive case the doc refuses).
  - copy without overlay (--overlay-rootfs 0): works. Restored desktop's a11y rows (400) == the copy's after A,
    boxes too; != after B (so it is the saved state); a further action works; DumpStatus done after stop; save 2.9 s,
    restore 1.5 s (+ wait_ready). traces/restore_test_o0/result.json.
- Pod whcbv4x3ak63un deleted (user: no pod while debugging); confirmed gone in list-pods. ssh tunnel closed.

## Smoke test, part 2: prefix cache via tfork-restore (2026-10-29)
- osw_run.py Podman.save/load (uncommitted; Vikranth's code): tfork / criu save = `clone --live --persistent=async
  --copies=1 --tfork-tcp-close` of the rollout copy, wait `.Tfork.DumpStatus` == done, `stop -t 0` (keeps the image);
  load = `container tfork-restore --name <name> <clone>` + wait_ready. stock-criu keeps the checkpoint tar. main():
  --prefix-cache with tfork refuses --overlay-rootfs 1 (an overlay copy can't be saved: see part 1).
- smoke_wuklab08.sh: replays use --overlay-rootfs 0; new stages control / uncache (cache entries are stopped
  containers that outlive the run; `uncache` removes them with the index).
- equiv_check.py: the taskbar clock label (wall-clock time) is masked; it was the only difference between any two
  runs (e.g. '6:20 PM' vs '6:52 PM'). Hit rate counted over finished rollouts.
- `smoke_prefix1` (replay, empty cache, depth 2): 4/4 saves (2.9-3.8 s), 0 hits (a group's two rollouts reach a
  prefix together; the other one is still saving it). vs smoke_live: rewards 4/4, observations 52/52.
- `smoke_prefix2` (replay, same cache): 8/8 steps <= depth served by tfork-restore (3.6-3.8 s gimp, 18-20 s calc
  incl. the observation), 0 restore failures. vs smoke_live: rewards 4/4, step counts 4/4, observations 52/52
  (boxes too), the observation right after a restored step 8/8. All rewards are 0 in this smoke (weak reward check).

## Smoke test, part 3: control and spec execution (2026-10-29)
- `smoke_control` (replay, both off, overlay 0) vs smoke_live: rewards 4/4, observations 52/52 (clock masked): a
  replay reproduces the recording exactly, so any difference under a feature is the feature's.
- `smoke_spec` (replay, --spec-exec 2, predictor and action book empty at start): 41 steps speculated (44 forks,
  0 errors), 37 hits (90%) -> 37/52 steps adopted from a fork (71%; gimp 11/22, calc 26/30); shadow scoring top-1
  35/52, top-2 37/52. vs smoke_live: rewards 4/4, step counts 4/4, observations 52/52 (boxes too), the observation
  right after an adopted step 34/34 (3 adopted steps were last steps). Cold start learns within the run because the
  agent repeats actions (gimp g0: 5 distinct action keys over 15 steps).
- osw_run.py `--spec-warm DIR...` (new, uncommitted): before the run, OnlineTage.warm(dirs) (its traj.jsonl parser
  fits osw_run's traj rows) + ActionBook.remember for every recorded action. Offline check: warmed from
  smoke_live, 52 reveals, 5 book keys; top-2 contains the recorded action at 14/15 steps of gimp g0. The 10-epoch
  loop needs osw_loop.py to pass --spec-warm <earlier epochs> each epoch (not done).
- equiv_check.py: spec funnel split into all-rollout event counts and finished-rollout step counts.
