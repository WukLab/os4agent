# OSWorld GRPO: in-memory prefix tree cache (tfork)

A GRPO group runs the same task K times (K = 8 here). Rollouts of one task often take the same first actions, and
every OSWorld step is slow desktop work: actions, a 2 s pause, and the accessibility tree, 9 to 25 s per step. The
prefix cache keeps the desktop state after common action prefixes as idle live tfork clones in memory. A rollout that
reaches a cached prefix forks that state (seconds) instead of replaying the steps. The cache lives across epochs, so
later epochs, whose policy repeats earlier trajectories, get more hits.

Everything below is `osw_run.py` (one epoch) and `osw_loop.py` (the live GRPO loop: rollouts on this host, vLLM and
training on a GPU pod).

## How it works

- **Key:** hash(system, task, the exact actions so far). Depth n = after n actions; depth 0 = the state after task
  setup.
- **Entry:** an idle live clone of a rollout's desktop (`podman container clone --live --copies=1`), plus the
  observation the step returned (the tool's reply).
- **Hit:**
  - `--prefix-lazy`: the rollout gets the saved reply at once and keeps going on replies. Its desktop is forked from
    the deepest hit only at its first miss, or at the end for the checker.
  - `--prefix-lazy-start`: a group whose after-setup state is cached forks no copies at all; each rollout gets its
    desktop at its first miss.
- **Shared clones:** rollouts that miss at the same snapshot within 1 s share one `--copies=k` clone.
- **Tree (`--prefix-tree`):** a prefix is saved only under a cached parent, and only leaves are evicted. A hit never
  depends on an evicted ancestor. A save whose parent is still being saved waits for it.
- **Admission (`--prefix-admit-cost N`):** save only where trajectories repeat:
  (rollouts that reached the parent − 1) × the desktop time from the after-setup state to this prefix ≥ N s.
  `--prefix-admit-visits` is a simpler visits threshold.
- **Eviction:**
  - The snapshots' PSS is kept under `--prefix-mem-budget-gib`.
  - `--prefix-policy gdsf` gives each entry the priority clock + step_s × (1 + hits); the clock rises to each
    victim's priority.
  - The order is schedule-aware: finished groups' entries go first, then pending groups' (latest-scheduled first),
    running groups' last, and roots last of all.
  - In tree mode a new save may evict only finished groups' non-root entries; otherwise the save is skipped
    (`no_room`).
- **Clone throttle:** `--clone-copies-limit N` caps the copies being cloned at once, first come first served, because
  many concurrent CRIU restores fail. `--order-by DIRS` / `osw_loop.py --longest-first` start the slowest groups
  first.

## The settings we use

```
--prefix-cache DIR --prefix-depth 8 --prefix-mem --prefix-lazy --prefix-lazy-start --prefix-tree
--prefix-policy gdsf --prefix-admit-cost 10 --prefix-mem-budget-gib 40
--overlay-rootfs 0 --clone-copies-limit 16 --parallel 8
```

Start every cache cold, with an empty cache dir (snapshots, `index.json`, `visits.json`) and no containers. The run
scripts do this. Each script's header says what it runs and where its results go.

## Scripts

| Script | What it does |
|---|---|
| `test_prefix_tree.sh [budget GiB]` | Smoke test: replays of `traces/smoke_live` (calc + gimp, 2 rollouts, no model), two epochs, a small budget to force evictions. `equiv_check.py` plus `tree_check.py` (tree invariant, forks per rollout, evictions). |
| `run_tree8_replay.sh`, `run_tree8_v3.sh`, `run_tree8_v4.sh` | Replays of a recorded 16 × 8 epoch through the depth-8 tree cache: how the settings evolved. |
| `run_tree8_same.sh`, `run_tree8_same2.sh` | Eviction check without model drift: fill the cache from one recording, replay the same recording again. `same_check.py` says what admission and eviction lost. `same2` is the current settings. |
| `run_team16_tree8.sh` | Live GRPO loop, 6 epochs, 16 tasks × 8, longest-first, current settings. Needs a GPU pod (`POD=root@ip PORT=…`) started with `pod_serve.sh`. |
| `run_team16_tree8f.sh` | The same in task-file order, to separate ordering from caching. |

Analysis:
- `tree_check.py` — cache invariants and evictions.
- `same_check.py` — what a second identical pass missed, and why.
- `hits_by_depth.py` — hit rate per step.
- `pmem_report.py` — memory per run.
- `timeline_breakdown.py` — where rollout time goes, with `--plot`.
- `mem_timeline.py` — memory over an epoch; `--pss`, `--desktop-pss --stack-cache --top-only`, `--counts`.
- `equiv_check.py` — a run against its recording: rewards, steps, observations.

Replays use `--replay <trace dir> --replay-latency 1`, which replays recorded model replies with their recorded
latency, so no GPU is needed. The task list is `grpo_batch16_team.json`: 6 Chrome, 4 GIMP and 6 LibreOffice Calc tasks.

## Results so far (wuklab-08: 64 cores, 247 GiB, overlay 0)

| Run | Rollout time | Notes |
|---|---|---|
| Replay, no cache (`split_e4_control`) | 15.3 min (14.4 longest-first) | baseline |
| Replay, tree cache filled from cold | 14.9 min | |
| Same recording again through that cache | 11.7 min (−19%) | steps 1–8: hit 41%, never saved 38%, evicted 22% |
| Live loop epoch 1, no cache (`team16_base_e1`) | 15.8 min | |
| Live loop epoch 1, tree cache, file order (`team16_tree8f_e1`) | 11.8 min (−28%) | 373 hits (40%), 0 errors |
| Live loop, tree cache, longest-first (`team16_tree8`) | epochs 0–4: 16.4 / 13.8 / 14.0 / 13.3 / 15.9 min | |

Memory in live epoch 1:

| | Tree cache | No cache |
|---|---|---|
| Live desktops' PSS, peak | 28 GiB | 45 GiB |
| Live desktops' PSS, mean | 16 GiB | 26 GiB |
| Cache snapshots' PSS | ~38–40 GiB (the budget) | — |
| Desktops + snapshots, peak | 66 GiB | 45 GiB |

## Known issues

- **Concurrent restores under heavy CPU load:** CRIU restores fail when many run at once under heavy CPU load (one
  wave of 16 groups: load 100–220 on 64 cores). The signatures are "restore wait aborted: participants=0" and
  "cgroupd recv error". Group forks retry; a failed save just isn't cached. Keep `--parallel 8` and
  `--clone-copies-limit 16`.
- **A rare save failure:** about 1 in 200 saves fails on one Chromium renderer region with `vma_cherrypick failed …
  -13` (`EACCES`). It is deterministic for that desktop and still under investigation.
- **One task's snapshots:** in `team16_tree8` epochs 2 and 3, task 6766f2b8's (Chrome) snapshots failed CRIU restore
  (6 and 8 errors).
- **`containers-os4agent.conf` is host-specific** and not in git; see `SETUP.md`.
- **Experimental, off by default:**
  - `osw_run.py --ro-rootfs 1` needs a podman `--tfork-ro-rootfs` change that is not pushed yet. It has a known bug:
    cache hits fail once the group's source is gone.
  - `--rootfs-check {log,ro}` is a test aid. Leave both off.
