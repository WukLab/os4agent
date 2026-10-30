"""Integrity check of a wa_record.py recording (and its --only redo dir): every (task, k) of the config has a rollout,
every file parses, steps are numbered 1..n and match result.json, per-step timestamps are ordered, chat.jsonl has a
record per step (prompt, reply, action, page rows), rewards are scored, and the sampler files cover the run.
  python3 check_traces.py <run dir> [<redo dir>]     exit 0 = intact"""
import glob, json, os, sys

RUN = sys.argv[1]
REDO = sys.argv[2] if len(sys.argv) > 2 else None
problems, notes = [], []


def jl(path):
    out, bad = [], 0
    for line in open(path):
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                bad += 1
    if bad:
        problems.append(f"{path}: {bad} unparsable lines")
    return out


def load(d):
    out = {}
    for rd in sorted(glob.glob(f"{d}/*__g*")):
        name = os.path.basename(rd)
        missing = [f for f in ("result.json", "steps.jsonl", "chat.jsonl") if not os.path.exists(f"{rd}/{f}")]
        if missing:
            problems.append(f"{name}: missing {missing}")
            continue
        try:
            r = json.load(open(f"{rd}/result.json"))
        except json.JSONDecodeError as e:
            problems.append(f"{name}: result.json unparsable ({e})")
            continue
        r["dir"], r["steps_rec"], r["chat"] = rd, jl(f"{rd}/steps.jsonl"), jl(f"{rd}/chat.jsonl")
        out[(r["task_id"], r["k"])] = r
    return out


cfg = json.load(open(f"{RUN}/config.json"))
R = load(RUN)
tasks = cfg["tasks"] if isinstance(cfg["tasks"], list) else [int(t) for t in str(cfg["tasks"]).split(",")]
want = {(t, k) for t in tasks for k in range(cfg["rollouts"])}
if REDO:
    for key, r in load(REDO).items():
        if key not in R:
            problems.append(f"redo has {key}, which is not in the run")
        elif R[key].get("error") or R[key].get("reward") is None:
            R[key] = r
        else:
            notes.append(f"redo {key} not used: the original is scored")
if set(R) != want:
    problems.append(f"rollouts: missing {sorted(want - set(R))}, extra {sorted(set(R) - want)}")

ORDER = ["t_obs_start", "t_obs_end", "t_llm_send", "t_first_token", "t_llm_done", "t_act_start", "t_act_end", "t_settle_end"]
for key, r in sorted(R.items()):
    tag, s = os.path.relpath(r["dir"], os.path.dirname(RUN)), r["steps_rec"]
    if r.get("error"):
        problems.append(f"{tag}: error {str(r['error'])[:80]}")
    if r.get("reward") is None:
        problems.append(f"{tag}: unscored ({str(r.get('eval_error'))[:80]})")
    if [x["step"] for x in s] != list(range(1, len(s) + 1)):
        problems.append(f"{tag}: step numbers {[x['step'] for x in s]}")
    if len(s) != r.get("steps"):
        problems.append(f"{tag}: {len(s)} step records, result.json says {r.get('steps')}")
    if not 1 <= len(s) <= cfg["max_steps"]:
        problems.append(f"{tag}: {len(s)} steps")
    for x in s:
        ts = [x.get(k) for k in ORDER]
        if None in ts:
            problems.append(f"{tag} step {x['step']}: missing {[k for k, v in zip(ORDER, ts) if v is None]}")
        elif any(b < a for a, b in zip(ts, ts[1:])):
            problems.append(f"{tag} step {x['step']}: timestamps out of order")
    if s and not (r["t_rollout_start"] <= s[0]["t_obs_start"] and s[-1]["t_settle_end"] <= r["t_rollout_end"] + 1):
        problems.append(f"{tag}: steps outside [t_rollout_start, t_rollout_end]")
    c = r["chat"]   # one record per step: prompt messages, response, parsed action, page rows
    if [x.get("step") for x in c] != [x["step"] for x in s]:
        problems.append(f"{tag}: chat.jsonl steps {[x.get('step') for x in c]} vs steps.jsonl {len(s)}")
    if any(not x.get("messages") or not x.get("response") or "action" not in x or not isinstance(x.get("rows"), list) for x in c):
        problems.append(f"{tag}: chat.jsonl record without messages / response / action / rows")

own = [r for r in R.values() if os.path.dirname(r["dir"]) == RUN.rstrip("/")]   # the samplers cover the run, not the redo
t0 = min(r["setup"]["t_start"] for r in own if "setup" in r)
t1 = max(r["t_rollout_end"] for r in own if "t_rollout_end" in r)
for f, period in (("mem.jsonl", 5), ("vllm.jsonl", 5), ("rtt.jsonl", 30), ("events.jsonl", None)):
    path = f"{RUN}/{f}"
    if not os.path.exists(path):
        problems.append(f"missing {f}")
        continue
    rows = jl(path)
    ts = [x["t"] for x in rows if "t" in x]
    line = f"{f}: {len(rows)} rows, {min(ts) - t0:+.0f} s .. {max(ts) - t1:+.0f} s around the run"
    if period:
        gaps = [b - a for a, b in zip(ts, ts[1:])]
        line += f", largest gap {max(gaps):.1f} s (period {period} s)"
        if max(gaps) > 4 * period:
            problems.append(f"{f}: gap of {max(gaps):.0f} s")
    if f == "events.jsonl":
        done = [x for x in rows if x.get("event") == "wave_rollouts_done"]
        line += f", {len(done)} waves done, run_done {'yes' if any(x.get('event') == 'run_done' for x in rows) else 'NO'}"
        if not any(x.get("event") == "run_done" for x in rows):
            problems.append("events.jsonl: no run_done")
    notes.append(line)

print(f"{RUN}" + (f" + {REDO}" if REDO else ""))
print(f"{len(R)} rollouts (want {len(want)}), {sum(len(r['steps_rec']) for r in R.values())} steps, "
      f"{len(R) - len(own)} from the redo; run {t1 - t0:.0f} s; "
      f"{sum(1 for r in R.values() for x in r['chat'] if not x['rows'])} steps saw a page with no rows")
for n in notes:
    print("  " + n)
print("INTACT" if not problems else f"{len(problems)} PROBLEMS:\n  " + "\n  ".join(problems[:60]))
sys.exit(1 if problems else 0)
