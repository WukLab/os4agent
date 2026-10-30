"""Does spec execution / the prefix cache change what the policy sees or the reward? And how often does each hit?

  venv/bin/python -I equiv_check.py RUN [REPLAY]

RUN: an osw_run.py result dir. REPLAY (optional): a replay of RUN's actions (--replay RUN) with the features off, or
the other way round. Per rollout (<domain>/<task>__g<k>) in both: reward equal, and per step whether the observation
the policy was prompted with is the same: the accessibility rows' (role, name) list, which is all the prompt shows
(boxes only place clicks, so they are compared separately). A step's observation is the one before its action, so a
step served by a fork or a checkpoint (traj.jsonl "skipped") is judged by the next step's observation and the reward.

Hit rates, from RUN alone:
  spec    per step: the predictor guessed (decide returned guesses) -> forks ran (a spec_exec event: guesses with code)
          -> the model's action was among them (hit) -> adopted (traj "skipped": "spec"); also fork errors and the
          predictor's top-1 / top-k accuracy (traj "spec", shadow scoring).
  prefix  prefix_hit / prefix_saved / *_failed events, and the hit rate over the steps a hit was possible
          (step <= --prefix-depth, an action with a key, not already served by speculation).
"""
import collections, json, re, sys
from pathlib import Path


def rollouts(run):
    for d in sorted(Path(run).glob("*/*__g*")):
        if (d / "result.txt").exists():
            yield f"{d.parent.name}/{d.name}", d


def jl(p):
    return [json.loads(l) for l in open(p) if l.strip()] if p.exists() else []


CLOCK = re.compile(r"^\d{1,2}:\d{2}( ?[AP]M)?$")  # the taskbar clock: wall-clock time, differs between any two runs
# the taskbar's date (label "10/30/26", button "Today is October 30, 2026"): differs from a recording made another day
DATE = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}|Today is \w+ \d{1,2}, \d{4})$")


def obs_rows(d):
    """Per step: ([(role, name)], [box]) of the observation the policy acted on; the clock's and date's text masked."""
    norm = lambda r: (r[0], "<clock>" if r[0] == "label" and CLOCK.match(r[1]) else
                      "<date>" if r[0] in ("label", "push-button") and DATE.match(r[1]) else r[1])
    return [([norm(r) for r in s.get("rows", [])], [tuple(r[2]) for r in s.get("rows", [])]) for s in jl(d / "chat.jsonl")]


def reward(d):
    return float(open(d / "result.txt").read().strip() or 0)


def compare(run, rep):
    A, B = dict(rollouts(run)), dict(rollouts(rep))
    both = sorted(set(A) & set(B))
    tot = collections.Counter()
    print(f"paired: {len(both)} rollouts in both ({len(A)} in {Path(run).name}, {len(B)} in {Path(rep).name})")
    for k in both:
        ra, rb = reward(A[k]), reward(B[k])
        oa, ob = obs_rows(A[k]), obs_rows(B[k])
        skipped = {s["step_num"]: s["skipped"] for s in jl(A[k] / "traj.jsonl") if s.get("skipped")}
        skipped.update({s["step_num"]: s["skipped"] + "(replay)" for s in jl(B[k] / "traj.jsonl") if s.get("skipped")})
        n = min(len(oa), len(ob))
        same = [oa[i][0] == ob[i][0] for i in range(n)]
        boxes = [oa[i][1] == ob[i][1] for i in range(n) if same[i]]
        after_skip = [same[i] for i in range(n) if i >= 1 and i in skipped]  # step i+1's observation follows step i
        first = next((i + 1 for i, s in enumerate(same) if not s), None)
        tot.update(rollouts=1, reward_same=ra == rb, steps=n, obs_same=sum(same), boxes_same=sum(boxes),
                   steps_len_same=len(oa) == len(ob), after_skip=len(after_skip), after_skip_same=sum(after_skip))
        flag = "" if ra == rb and all(same) and len(oa) == len(ob) else "   <-- differs"
        print(f"  {k:60s} reward {ra:g}/{rb:g} steps {len(oa)}/{len(ob)} obs same {sum(same)}/{n}"
              f"{f' (first diff step {first})' if first else ''} served {dict(sorted(skipped.items())) or '-'}{flag}")
    t = tot
    print(f"rewards equal {t['reward_same']}/{t['rollouts']}; step counts equal {t['steps_len_same']}/{t['rollouts']}; "
          f"observations same {t['obs_same']}/{t['steps']} steps (boxes too: {t['boxes_same']}); "
          f"observations right after a served step same {t['after_skip_same']}/{t['after_skip']}")


def hit_rates(run):
    R = Path(run)
    cfg = json.load(open(R / "config.json"))
    ev = jl(R / "events.jsonl")
    by = collections.Counter(e["event"] for e in ev)
    steps = [s for _, d in rollouts(R) for s in jl(d / "traj.jsonl")]  # finished rollouts only
    served = collections.Counter(s.get("skipped") for s in steps if s.get("skipped"))
    print(f"{R.name}: system {cfg['system']}, spec-exec {cfg.get('spec_exec', 0)}, prefix-cache "
          f"{cfg.get('prefix_cache') or '-'} (depth {cfg.get('prefix_depth')}), {len(steps)} steps, served {dict(served) or '-'}")
    sp = [s["spec"] for s in steps if s.get("spec")]
    if sp:
        k = cfg.get("spec_exec") or cfg.get("spec_topk")
        print(f"  predictor (shadow scoring over {len(sp)} actions): top-1 {sum(x['hit1'] for x in sp)}, "
              f"top-{len(sp[0]['guesses']) if sp[0]['guesses'] else k} {sum(x['hitk'] for x in sp)}, "
              f"top-{k} {sum(x['key'] in x['guesses'][:k] for x in sp)}, actions never seen before in the rollout "
              f"{sum(x['new'] for x in sp)}")
    if cfg.get("spec_exec"):
        se = [e for e in ev if e["event"] == "spec_exec"]
        hits = [e for e in se if e.get("hit") is not None]
        print(f"  spec execution, all rollouts (events): {len(se)} steps speculated ({sum(e['guesses'] for e in se)} forks, "
              f"{sum(1 for e in se if e.get('error'))} with an error) -> {len(hits)} hits "
              f"({100 * len(hits) / max(len(se), 1):.1f}%)")
        print(f"  spec execution, finished rollouts: {len(steps)} steps, {sum(1 for x in sp if x['guesses'])} with guesses, "
              f"{served.get('spec', 0)} adopted ({100 * served.get('spec', 0) / max(len(steps), 1):.1f}% of steps)")
        for e in [e for e in se if e.get("error")][:3]:
            print(f"    error: {e['error'][-200:]}")
    if cfg.get("prefix_cache"):
        depth = cfg.get("prefix_depth", 3)
        elig = [s for s in steps if s["step_num"] <= depth and json.loads(s["action"]).get("action") not in ("done",)
                and s.get("skipped") != "spec"]
        print(f"  prefix cache (all rollouts): {by['prefix_hit']} hits, {by['prefix_saved']} saved, {by['prefix_save_failed']} "
              f"save failures, {by['prefix_restore_failed']} restore failures; finished rollouts: {served.get('prefix', 0)} "
              f"of {len(elig)} steps <= depth {depth} served from the cache ({100 * served.get('prefix', 0) / max(len(elig), 1):.1f}%)")
        for e in [e for e in ev if e["event"] in ("prefix_save_failed", "prefix_restore_failed")][:3]:
            print(f"    {e['event']}: {e['error'][-200:]}")
    errs = [e for e in ev if e["event"] == "rollout_done" and e.get("error")]
    print(f"  rollouts {by['rollout_done']}, errors {len(errs)}, group errors {by['group_error']}, "
          f"mean reward {sum(e['reward'] for e in ev if e['event'] == 'rollout_done') / max(by['rollout_done'], 1):.3f}")
    for e in errs[:3]:
        print(f"    rollout error: {e['task'][:8]} g{e['k']}: {e['error'][-200:]}")


if __name__ == "__main__":
    hit_rates(sys.argv[1])
    if len(sys.argv) > 2:
        compare(sys.argv[1], sys.argv[2])
