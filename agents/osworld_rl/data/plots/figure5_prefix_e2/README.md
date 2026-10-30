# Epoch 2: tfork vs tfork + speculation vs tfork + prefix cache, OSWorld 16x8

Second recorded epoch (16 tasks x 8, `grpo16.json`, step cap 20, policy `grpo_think_reg-pol3s`). Recorded 2026-10-30.
- **tfork** = the live recording `rec128e2_shot` (no speculation, live vLLM on one H100).
- **tfork + speculation** = `r128e2_P2`: replay with recorded model-call times, P2 pre-fork speculation, TAGE warmed on
  the previous epoch only.
- **tfork + prefix cache** = `r128e2_SC2`: replay with recorded model-call times, screen cache
  (`--screen-cache 1`): key = (task, accessibility tree with the clock masked, action); a hit gives the model the
  cached next screen at once while the rollout's own desktop runs the action in the background; the real screen is
  checked before the next step goes on (mismatch: the model call is redone on the real screen). Warmed from every
  earlier recorded trace except epoch 2 itself. No extra forks.

## Files
- `spec_batch_log_prefix`, `spec_batch_prefix`: rollouts still running (log / linear); `spec_memory_prefix`: working set.
- `data/{rec128e2_shot,r128e2_P2,r128e2_SC2}/`: events.jsonl, mem.jsonl, config.json.
- `sys_plot.py`: `python3 sys_plot.py . prefix "tfork=data/rec128e2_shot" "tfork + speculation=data/r128e2_P2" "tfork + prefix cache=data/r128e2_SC2"`
- `cmp_runs.py` (the table below), `run_e2_P2.sh`, `run_e2_SC2.sh`.

## Results (no rollout excluded)
| | live | tfork + speculation | tfork + prefix cache |
|---|---|---|---|
| epoch (last rollout done) (min) | 20.78 | 19.21 (-7.5%) | 16.96 (-18.4%) |
| 99% of rollouts done (min) | 19.19 | 18.06 (-5.9%) | 15.47 (-19.4%) |
| tail from 32 left (min) | 5.84 | 4.28 (-26.7%) | 3.67 (-37.2%) |
| tail from 16 left (min) | 4.67 | 3.27 (-29.9%) | 2.89 (-38.2%) |
| peak working set (GiB) | 69.43 | 69.85 (+0.6%) | 70.08 (+0.9%) |
| working set x time (GiB-min) | 843 | 860 (+2.0%) | 744 (-11.7%) |
| solved (/128) | 45 | 45 | 45 |
rewards identical to live: tfork + speculation 128/128, tfork + prefix cache 128/128

Prefix cache: ~66% of steps served from the cache, ~7% of checks rejected (each costs one repeated model call).

## Caveats
- The prefix cache was warmed from every earlier recorded trace except epoch 2 (epoch 1 = `rec128_shot` plus 13 older
  test traces, 4940 entries). Epoch 1 alone gives 57% vs 60% hits offline; the trace simulator (`prefix_sim.py
  --key screen`) gives the same epoch time for both (-17.2%): the extra traces only add hits in rollouts that don't
  decide when the epoch ends.
- Both optimizations are replays with recorded model-call times (GPU queueing not modeled); the baseline is the live
  run (on epoch 1 a no-speculation replay matched its live run within 0.5%).
- One run per arm.
- The first prefix-cache run had ~1.5 s/step harness overhead (GIL saturated by re-parsing trees); this is the rerun
  with parsing memoized (overhead ~0 s/step).
