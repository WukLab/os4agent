# Figure 5: speculation (pre-fork, P2 settings) vs no speculation, OSWorld 16x8

One epoch of 128 rollouts (16 tasks x 8, `grpo16.json`), step cap 20, recorded live once (`rec128_shot`,
policy `grpo_think_reg-pol2`, fp16 merged, vLLM eager on one H100), then replayed twice on 06 with the recorded
model-call times: **A** = no speculation, **P2** = speculation. Same trajectories in both; the replay of A matches
the live recording (epoch 18.3 vs 18.4 min). Recorded 2026-10-30.

## Files
- `spec_batch_log.png/.svg`: rollouts still running (log scale) over time. Main timing figure.
- `spec_batch.png/.svg`: the same on a linear axis, with an inset on the tail.
- `spec_memory.png/.svg`: environments' cgroup working set over time (every desktop, speculation copies included).
- `spec_reward.png/.svg`: per-task success rate (of 8 rollouts), no speculation vs speculation. `rewards.csv`: every
  rollout's reward in both runs. `python3 spec_reward.py OUT data/r128_A data/r128_P2`
- `rollout_finish_times.csv`, `memory_working_set.csv`: the data behind the plots.
- `data/{r128_A,r128_P2,rec128_shot}/`: events.jsonl, mem.jsonl, config.json of each run.
- `spec_plot.py` (+ `timeline_plot.py` for styling): `python3 spec_plot.py OUT data/r128_A data/r128_P2 7a4e4bc8:0`
- `run_128A.sh`, `run_128P2.sh`: the replay commands; `grpo16.json`: the task set.

## P2 speculation settings
`--spec tage --spec-exec 1 --spec-prefork 1 --spec-from 3 --spec-slow 1 --spec-priority 1 --spec-max-forks 24
--spec-fork-inflight 2 --spec-fork-inflight-tail 8`
Pre-fork: the idle desktop is forked while the model thinks; the copy runs the chosen action and TAGE's guess for
the next one; a hit adopts the copy (race with the real desktop if it is not done yet), a miss drops it. No
speculation until every rollout has started; at most 2 forks in flight while more than half the batch is live,
8 after; at most 24 copies alive; copies go to rollouts projected to finish last.

## Results (batch plots and timings exclude one rollout, see below)
| | no speculation | speculation (P2) | change |
|---|---|---|---|
| epoch (last rollout done) | 17.97 min | 16.71 min | **-7.0%** |
| 99% of rollouts done | 17.17 min | 16.33 min | -4.9% |
| tail from 64 rollouts left | 6.52 min | 5.27 min | -19% |
| tail from 32 rollouts left | 4.25 min | 3.00 min | **-29%** |
| tail from 16 rollouts left | 2.11 min | 1.56 min | -26% |
| peak working set | 69.4 GiB | 72.1 GiB | +2.7 GiB (+4%) |
| working set, minutes 2-15 | | | ~+2.5 GiB (+4-9%) |
| working set, tail (15-18 min) | 9.0 GiB | 6.7 GiB | -26% |
| total GiB-minutes | 783 | 809 | +3.4% |

Rewards: identical for all 128 rollouts (52 solved, mean 0.406 in both): speculation changed no outcome.
Speculation: 62 hits (42 ready, 20 race wins), 53 misses, 57 no usable guess, 0 errors, 0 copies left behind.
The curves overlap until ~32 rollouts are left: while the GPU is saturated (model calls ~25 s) saved env time is
absorbed by queueing; the gain is in the latency-bound tail.

## Caveats
- **Single epoch:** one recorded epoch (one policy snapshot, no training in between), replayed with and without
  speculation. Not measured across several GRPO epochs.
- **Excluded rollout:** `7a4e4bc8` (Calc reorder columns) k=0 has one same-element drag (step 16, drag from a cell
  onto itself) that takes ~128 s in every run (LibreOffice/GTK3 waits ~2 min before cancelling the drop). It ends
  the epoch at ~18.2-18.3 min in both arms; with it the raw epoch change is -0.2%. Fixed afterwards in
  a11y_owl_agent.py (a same-element drag is now a no-op); not yet re-measured with the fix.
- One run per arm: run-to-run noise between two runs without speculation is a few % at single points.
- One rollout per arm hit the known accessibility-tree hang (Chrome `030eeff7`, 120 s timeout), same in both.
- A setting with 48 copies (P3) gave -6.3% epoch / -5.5% at 99%: no measurable difference from P2.
