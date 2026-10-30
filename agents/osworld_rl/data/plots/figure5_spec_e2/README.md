# Figure 5, epoch 2: tfork vs tfork + speculation (P2), OSWorld 16x8

Second recorded epoch (16 tasks x 8, `grpo16.json`, step cap 20), policy `grpo_think_reg-pol3s` (one GRPO update on
epoch 1 = `rec128_shot`). Recorded 2026-10-30.
- **tfork** = the live recording `rec128e2_shot` (tfork, no speculation, live vLLM on one H100). No separate
  no-speculation replay: on epoch 1 the replay matched the live run (18.3 vs 18.4 min).
- **tfork + speculation (ours)** = `r128e2_P2`, replay of `rec128e2_shot` with the recorded model-call times and P2
  settings; TAGE warmed only on the previous epoch (`rec128_shot`).

## Files
- `spec_batch_log_e2`, `spec_batch_e2`: rollouts still running (log / linear) over time.
- `spec_memory_e2`: environments' cgroup working set over time.
- `data/{rec128e2_shot,r128e2_P2}/`: events.jsonl, mem.jsonl, config.json.
- `sys_plot.py` (+ `timeline_plot.py`): `python3 sys_plot.py . e2 "tfork=data/rec128e2_shot" "tfork + speculation (ours)=data/r128e2_P2"`
- `run_e2.sh` (live recording; its replays were not run), `run_e2_P2.sh` (speculation replay), `grpo16.json`.

## Results (no rollout excluded)
| | tfork (live) | + speculation | change |
|---|---|---|---|
| epoch (last rollout done) | 20.78 min | 19.21 min | **-7.6%** |
| 99% of rollouts done | 19.19 | 18.06 | -5.9% |
| tail from 32 rollouts left | 5.84 | 4.28 | -27% |
| tail from 16 rollouts left | 4.67 | 3.27 | **-30%** |
| peak working set | 69.4 GiB | 69.9 GiB | +0.7% |
| solved | 45/128 | 45/128 | identical rewards |

Speculation: 40 hits, 28 race wins, 53 misses, 47 no guess, 9 not ready.
The last rollout (7a4e4bc8 k=4, Calc reorder columns) has slow ordinary clicks (33-50 s) in both runs: real env time,
not the old same-element-drag stall (now a no-op), so nothing is excluded.

## Caveats
- Baseline is the live run, speculation is a replay: compares like epoch 1's replay/live agreement (~0.5%).
- One run per arm.
