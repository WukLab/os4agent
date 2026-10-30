"""Offline sanity check of in-place speculation on a recorded run: replay TAGE (warmed like --spec-warm) over the
run's steps in time order; a top-1 hit at step >= FROM while fewer than BELOW rollouts are live saves min(env, model)
seconds (in-place: the guess runs on the live desktop while the model thinks). Report hit rate, per-rollout savings,
and the epoch/tail before vs after, measured on the run's real finish times. Usage: spec_sim.py <run> <warm,dirs> [below]"""
import json, glob, os, sys
sys.path.insert(0, "/mnt/ssd2/vikranth/osworld")
from toolspec.online import OnlineTage, web_step
run, warm = sys.argv[1], sys.argv[2].split(",")
BELOW, FROM = int(sys.argv[3]) if len(sys.argv) > 3 else 10**9, 3
D, B = float(os.environ.get("D", 0)), float(os.environ.get("B", 0))  # guess start delay; backup ready time
TOPK, EARLY = int(os.environ.get("TOPK", 1)), os.environ.get("EARLY", "0") == "1"
T = OnlineTage(topk=2)
T.warm([f"traces/{w}" for w in warm])
ev = [json.loads(l) for l in open(f"traces/{run}/events.jsonl")]
t0 = ev[0]["t"]
end = {(e["task"], e["k"]): e["t"] - t0 for e in ev if e["event"] == "rollout_done" and not e.get("error")}
steps = []
for d in glob.glob(f"traces/{run}/*/*__g*"):
    task, k = os.path.basename(d).split("__g")
    chat = [json.loads(l) for l in open(d + "/chat.jsonl")]
    for i, s in enumerate(json.loads(l) for l in open(d + "/traj.jsonl") if l.strip()):
        if i < len(chat) and chat[i].get("t") and "exec_s" in s:
            c = chat[i]["t"]
            steps.append((c["llm_start"] - t0, d, task, int(k), s, c["llm_end"] - c["llm_start"], s["exec_s"]))
steps.sort(key=lambda x: x[0])
prev_e = {}  # rollout -> env time of its previous step (early start: the guess also overlaps that step)
for t, d, task, k, s, w, e in sorted(steps, key=lambda x: (x[1], x[4].get("step_num", 0))):
    prev_e[(d, s.get("step_num", 0))] = e
saved, hits, n_spec = {}, 0, 0
for t, d, task, k, s, w, e in steps:
    rid = f"run:{d}"
    g = T.decide(task, rid)["guesses"]
    _, key = web_step(d, s)
    rec = T.reveal_key(task, rid, key)
    live = sum(1 for v in end.values() if v > t)
    if s.get("step_num", 0) >= FROM and live < BELOW and key is not None:
        n_spec += 1
        hit = rec and (rec["hit1"] or (TOPK >= 2 and rec["hitk"]))
        if EARLY: w = w + prev_e.get((d, s.get("step_num", 0) - 1), 0)
        if hit:
            hits += 1
            saved[(task, k)] = saved.get((task, k), 0) + min(e, max(0.0, w - D))
        else:  # miss: the real action waits for the backup to be ready
            saved[(task, k)] = saved.get((task, k), 0) - max(0.0, B - w)
print(f"TAGE over {len(steps)} steps: top-1 {T.summary()['hit1_pct']:.0f}%, top-2 {T.summary()['hit2_pct']:.0f}%")
print(f"speculated steps (step >= {FROM}, live < {BELOW}): {n_spec}, top-1 hits {hits} ({100 * hits / max(n_spec, 1):.0f}%), env time saved {sum(saved.values()) / 60:.1f} min")
base = sorted(end.values()); new = sorted(v - saved.get(k, 0) for k, v in end.items())
for name, d in (("baseline", base), ("in-place spec", new)):
    n, last = len(d), d[-1]
    print(f"  {name:14}: epoch {last / 60:5.1f} min | tail after 50% {100 * (last - d[n // 2 - 1]) / last:3.0f}%  "
          f"75% {100 * (last - d[int(n * .75) - 1]) / last:3.0f}%  90% {100 * (last - d[int(n * .9) - 1]) / last:3.0f}%")
for kk, v in sorted(end.items(), key=lambda x: -x[1])[:6]:
    print(f"  last rollouts: {kk[0][:8]} g{kk[1]} ends {v/60:5.1f} min, saved {saved.get(kk, 0)/60:4.1f} min")
print(f"  epoch change {100 * (new[-1] - base[-1]) / base[-1]:+.0f}%")
