"""Summary of a wa_record.py recording: counts, rewards, environment setup, per-step timing split, per-rollout time.
  python3 summarize_traces.py <run dir> [<redo dir>]    -> <run dir>/summary.md
A redo dir (wa_record.py --only) replaces the run's rollouts that ended in an error or unscored."""
import collections, glob, json, os, statistics as st, sys

RUN = sys.argv[1]
REDO = sys.argv[2] if len(sys.argv) > 2 else None


def rollouts(d):
    out = {}
    for f in glob.glob(f"{d}/*__g*/result.json"):
        r = json.load(open(f))
        r["steps_rec"] = [json.loads(l) for l in open(os.path.join(os.path.dirname(f), "steps.jsonl")) if l.strip()]
        r["src"] = os.path.basename(d)
        out[(r["task_id"], r["k"])] = r
    return out


R = rollouts(RUN)
redone = 0
if REDO:
    for key, r in rollouts(REDO).items():
        if key in R and (R[key].get("error") or R[key].get("reward") is None):
            R[key] = r
            redone += 1


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else float("nan")


def row(name, xs):
    return f"| {name} | {st.median(xs):.2f} | {q(xs, 0.9):.2f} | {q(xs, 0.99):.2f} | {sum(xs):.0f} |"


steps = [s for r in R.values() for s in r["steps_rec"]]
parts = {
    "observe page (rows + tabs)": [s["t_obs_end"] - s["t_obs_start"] for s in steps],
    "model: send → first token": [s["t_first_token"] - s["t_llm_send"] for s in steps],
    "model: first token → done (decode)": [s["t_llm_done"] - s["t_first_token"] for s in steps],
    "action (Playwright)": [s["t_act_end"] - s["t_act_start"] for s in steps],
    "settle (load + 1 s sleep)": [s["t_settle_end"] - s["t_act_end"] for s in steps],
}
total = sum(sum(v) for v in parts.values())
setup = {k: [] for k in ("container", "mysql", "base_url + flush", "first page", "site setup total (before the wave barrier)",
                          "wait for the rest of the wave", "login (after the barrier)", "start page (after the barrier)")}
for r in R.values():
    s = r["setup"]
    if "t_ready" not in s:
        continue
    t0 = s.get("t_setup_slot", s["t_start"])
    setup["container"].append(s["t_container_up"] - t0)
    setup["mysql"].append(s["t_mysql_up"] - s["t_container_up"])
    setup["base_url + flush"].append(s["t_base_url_done"] - s["t_mysql_up"])
    setup["first page"].append(s["t_first_page"] - s["t_base_url_done"])
    setup["site setup total (before the wave barrier)"].append(s["t_first_page"] - t0)
    setup["wait for the rest of the wave"].append(s["t_cdp"] - s["t_first_page"])
    setup["login (after the barrier)"].append(s["t_login_done"] - s["t_cdp"])
    setup["start page (after the barrier)"].append(s["t_ready"] - s["t_login_done"])
dur = [r["t_rollout_end"] - r["t_rollout_start"] for r in R.values() if "t_rollout_end" in r]
rewards = collections.Counter(r.get("reward") for r in R.values())
by_task = collections.defaultdict(list)
for r in R.values():
    by_task[r["task_id"]].append(r.get("reward") or 0)
nsteps = collections.Counter(len(r["steps_rec"]) for r in R.values())
stops = collections.Counter(r.get("stop") for r in R.values())
cfg = json.load(open(f"{RUN}/config.json"))

L = [f"# Trace summary: {os.path.basename(RUN)}", "",
     f"- {len(R)} rollouts ({len(by_task)} tasks × {cfg['rollouts']}), batch {cfg['groups_at_once'] * cfg['rollouts']} "
     f"({cfg['groups_at_once']} groups per wave), max {cfg['max_steps']} steps; model {cfg['model']} at {cfg['llm_url']}.",
     f"- {redone} rollouts replaced from the redo run `{os.path.basename(REDO)}` (their originals ended in an error)." if REDO else "",
     f"- Rewards: {dict(rewards)}; errors left: {sum(1 for r in R.values() if r.get('error'))}. Stop: {dict(stops)}.",
     f"- Steps per rollout: {dict(sorted(nsteps.items()))}; {len(steps)} steps in all.", "",
     "## Per step (seconds)", "", "| part | median | p90 | p99 | sum | share |", "|---|---|---|---|---|---|"]
L += [row(k, v)[:-2] + f" | {100 * sum(v) / total:.1f}% |" for k, v in parts.items()]
tokens_p = [s["prompt_tokens"] for s in steps if s.get("prompt_tokens")]
tokens_c = [s["completion_tokens"] for s in steps if s.get("completion_tokens")]
L += ["", f"Model share of step time: {100 * (sum(parts['model: send → first token']) + sum(parts['model: first token → done (decode)'])) / total:.1f}%; "
          f"prompt tokens median {st.median(tokens_p):.0f} (p90 {q(tokens_p, 0.9):.0f}), completion median {st.median(tokens_c):.0f} (p90 {q(tokens_c, 0.9):.0f}).",
      "", "## Environment setup (seconds, no fork: every rollout sets up its own; site setup runs 8 at a time, "
      "then all rollouts of the wave log in and open their start page together)", "",
      "| phase | median | p90 | p99 | sum |", "|---|---|---|---|---|"]
L += [row(k, v) for k, v in setup.items() if v]
L += ["", "## Rollout duration (seconds, from ready to last step)", "", "| | median | p90 | p99 | sum |", "|---|---|---|---|---|",
      row("rollout", dur), "", "## Success rate per task (of 8)", "",
      " ".join(f"{t}:{sum(1 for x in v if x == 1.0)}" for t, v in sorted(by_task.items()))]
rtt = [json.loads(l).get("rtt_s") for l in open(f"{RUN}/rtt.jsonl") if "rtt_s" in l]
L += ["", f"Network round trip to the model server (GET /v1/models every 30 s): median {st.median(rtt):.3f} s, "
          f"p90 {q(rtt, 0.9):.3f} s ({len(rtt)} samples). Included in the model times above."]
open(f"{RUN}/summary.md", "w").write("\n".join(x for x in L if x is not None) + "\n")
print("\n".join(L))
