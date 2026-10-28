# Group-tree speculation for GUI-agent GRPO rollouts (state sharing + prediction)

Assumes CoW VM fork (live clone, shared memory). Evidence: `sim_spec.py`, `analyze_share.py`, `analyze_markov.py` on `traces/grpo_mb2`
(10 tasks x 8 rollouts, UI-TARS-1.5-7B, T=1.0). Numbers are replay estimates; nothing was executed.

## Idea
All G rollouts of a task start from the same VM state and 62% still share their history after step 0 (35% at steps 1-2, 14% at 3-5, 0% from 6).
Treat the group as a **tree of VM states**: node = (task, action history), edge = action. Every executed or speculated edge leaves a CoW checkpoint.
A rollout whose real action matches an existing edge **adopts** that checkpoint instead of executing. Speculation just pre-builds edges.

## Data structures (per group)
- `tree[node] -> {launch_time, ready_time, checkpoint, obs(screenshot, a11y), owner}` per edge `(node, action_key)`.
- `action_key`: click -> `click@role|name` (a11y element, fallback to 40 px grid if unmapped); hotkey/write -> exact code. DONE/FAIL never speculated.
- Predictor tables, trained on other tasks only: Markov (prev 1-2 abstract actions), click propensity `P(click e | e visible)`.

## Per-step algorithm (rollout r at node N, state ready at t_ready)
1. On first arrival at N (T_N): checkpoint N. Build candidates = Markov-feasible (element visible in N's a11y tree) union propensity, each with probability p.
   Launch a branch (clone, execute, checkpoint) for every candidate with `p >= theta` (cap Bmax). Each branch costs ~V VM-seconds. Shared by every rollout at N.
2. Concurrently r calls the LLM (~4.7 s). Siblings at N also run; each sibling's real action creates an edge when it executes.
3. LLM returns real action a*. Look up edge (N, key(a*)):
   - exists, not r's own: **adopt** = fork its checkpoint into r's VM; wait only for `max(0, launch + V - now)`; saved = clip(t_real - launch, 0, V) - c_fork. Adopt only if saved > 0.
   - else: execute a* on r's own VM, checkpoint it as a new edge (siblings may adopt it later).
4. Discard checkpoints of edges nobody adopted once every rollout in the group has left N.
5. Update predictor tables and per-source hit counters online (calibrates theta).

## Safety rules (needed for reward fidelity)
- Element-level equivalence only for click-like actions on discrete widgets (button, menu-item, list-item, tab, link). For entry/text/slider/canvas/drag require
  coordinates within ~3 px, else execute normally. Hotkeys and typed text must match exactly.
- Match requires identical history keys, so same likely UI state. Optionally verify with a screenshot diff (adopted pairs: median diff 0.00, 97% <= 2/255).
- Log which steps were adopted/speculated and the real vs adopted action, so training can mask or audit them.
- Never speculate DONE/FAIL. Disable speculation if the env is nondeterministic (clock, network) for that task.

## Expected gain (sim_spec.py, c_fork = c_clone = 0.5 s, V = 9.1 s, LLM p50 = 4.7 s)
| Policy | Step time saved | Spec branches/step | Wasted | Extra VM-seconds |
|---|---|---|---|---|
| adopt only (sibling edges) | 8.5% | 0 | 0 | 0% |
| + predicted, theta=0.5 | 8.9% | 0.10 | 0.08 | 8% |
| + predicted, theta=0.3 | 9.0% | 0.16 | 0.14 | 14% |
| + predicted, theta=0.2 | 9.9% | 0.71 | 0.66 | 66% |
| + predicted, theta=0.1 | 10.8% | 1.71 | 1.65 | 165% |
| + predicted, B=8 (no gate, theta=0.02) | 13.0% | 5.66 | 5.54 | 554% |
Fork cost sensitivity (gated by step index): 0.2 s -> 9.8%, 1 s -> 8.6%, 3 s -> 6.1%, 6 s -> 2.9%.
Recommended start: adopt + theta ~0.2-0.3 (about 9-10% for at most +66% VM work).

## What this does not fix (bigger levers)
- ~110 s of ~264 s per rollout is reset + 60 s wait + setup, repeated by all siblings: fork one post-setup VM per group (same CoW mechanism).
- VM side is ~9 s/step: 3 s fixed sleep, a11y fetch 1.5-12 s. A settle poll and parallel a11y fetch beat speculation per unit effort.

## Open questions
- Real fork latency for a QEMU/KVM container with CoW memory (assumed 0.5 s; below ~3 s it pays off).
- Per-step checkpoint cost x 8 rollouts; branch CPU interference with real steps (host CPU was 13% busy at 8 envs).
- Training effect of element-level (not pixel-exact) action substitution.

---
# Addendum: how to reach 40-50% (composite, not action speculation alone)

Measured ceilings on grpo_mb2: lockstep dedup of identical (history, action) = 19.1% of executions (62% at step 0, 35% at 1-2, 14% at 3-5, 0% from 6; 457/514 nodes have 1 rollout);
oracle sibling action hit = 45.5%; best predicted+adopt policy = 13% of step time. Action speculation cannot reach 40-50% with independent T=1.0 rollouts.

Per-rollout wall time today (measured, 80 rollouts / 8 envs / 44 min): ~264 s = ~113 s reset+60 s wait+setup, ~123 s active (9.8 steps x ~12.6 s), ~28 s settle+eval.
Step = LLM 4.7 s + VM side 9.1 s (3 s fixed sleep, a11y fetch 1.5-12 s, screenshot 0.4 s, action+IO ~2 s).

| # | Change | Per-rollout time | Cumulative | Basis |
|---|---|---|---|---|
| 0 | baseline | 264 s | - | measured |
| 1 | a11y fetch off the critical path (model only needs the screenshot): start it right after the screenshot, join before the action runs | -2.5 s x 9.8 = -25 s | 239 s (-9%) | fetch 1.4-1.7 s typ, 4-12 s tails measured; the join may wait on tails |
| 2 | settle-poll (frame-diff) instead of fixed 3 s and fixed 20 s pre-eval sleep | -2 s x 9.8 + 18 s = -38 s | 201 s (-24%) | assumes settle ~1 s; check pass rates |
| 3 | fork ONE post-setup VM per group + pipelined reset | 113 s -> ~15 s | 103 s (-61%) | assumes CoW fork+pool ~15 s; unmeasured |
| 4 | tree-structured rollouts: branch the group at depth 3 (share steps 0-2 by construction, as Tree-GRPO/TreeRL) | -3 x 7/8 = -2.6 of 9.8 steps (-27% of active) | ~85 s (-68%) | saves LLM calls AND VM steps; correlates siblings (RL tradeoff) |
| 5 | adopt + gated prediction (SPEC_DESIGN.md) | ~-9% of remaining step time | ~80 s | sim_spec.py (overlaps with 4 -> not additive) |

Without #3 (needs unproven CoW QEMU fork): 1+2+4 reach ~-37%. With #3: >60%. 40-50% is reached by #1+#2+#3 alone; #4/#5 are the actual speculation layer on top.
