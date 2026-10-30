"""Offline: what pre-fork speculation would add on top of a screen-cache run (no desktops).

  venv/bin/python combo_sim.py SC_RUN RECORDING TAGE_WARM_DIR[,DIR...]

SC_RUN is a finished --screen-cache replay (e.g. traces/r128e2_SC2): its steps say which were served from the cache
(hit) and which ran on the desktop (miss), with their env times; scache_check events give the background time of each
hit. RECORDING is the live trace it replayed (model-call times, screens). Replays use fixed recorded model times, so a
rollout ends earlier by exactly the env time speculation takes off its critical path; the epoch is the last rollout.

Speculation for step i (a miss) happens in a copy forked while the model thinks about action i-1: the copy runs action
i-1, then TAGE's guess for i. If the guess is right the rollout adopts the copy at decision i (no env wait for i).
Rules (which steps i can be covered):
  v1      the pre-fork at i-1 needs step i-1 to be a miss (desktop idle), and is dropped if i-1 is a hit
  keep    the pre-fork is also made at a hit step and kept: the copy runs the hit action itself, then the guess
Saving for a covered miss i with a right guess (e = env time of the action on a desktop, t = model time of step i):
  i-1 a miss: real = e[i-1] + t + e[i], copy ready at e[i-1] + e[i]           -> saves min(e[i], t)
  i-1 a hit : real = max(t, e[i-1]) + e[i] (waits for the background run), copy ready at e[i-1] + e[i]
              -> saves max(t, e[i-1]) + e[i] - max(t, e[i-1] + e[i])
Filters: topk (forks per step), tail (only while <= 32 rollouts are live, as P2's in-flight cap), skip_cached (at a hit,
the served next screen is known: skip the fork when (that screen, guess) is in the cache -- the cache will serve it).
"""
import glob, hashlib, json, os, re, sys
from collections import defaultdict
import datetime as dt

sys.path[:0] = ["/mnt/ssd2/vikranth/osworld"]
from toolspec.online import OnlineTage  # noqa: E402
from toolspec.keys import action_key  # noqa: E402

sc, rec, warm = sys.argv[1], sys.argv[2], sys.argv[3].split(",")
CLOCK = re.compile(r"\b\d{1,2}:\d{2}( [AP]M)?\b")


def screen(chat_line):
    msgs = chat_line.get("messages")
    if not msgs:
        return None
    c = msgs[-1]["content"]
    c = c[-1]["text"] if isinstance(c, list) else c
    if "Accessibility tree:\n" not in c:
        return None
    return hashlib.sha1(CLOCK.sub("", c.split("Accessibility tree:\n", 1)[1].rsplit("\n\nNext action?", 1)[0]).encode()).hexdigest()


ts = lambda s: dt.datetime.strptime(s["action_timestamp"], "%Y%m%d@%H%M%S%f").timestamp()
ev = [json.loads(l) for l in open(f"{sc}/events.jsonl")]
t0 = ev[0]["t"]
bg = {(e["task"], e["k"], e["step"]): e["bg_s"] for e in ev if e["event"] == "scache_check"}
end = {(e["task"], e["k"]): e["t"] - t0 for e in ev if e["event"] == "rollout_done"}
ends_sorted = sorted(end.values())

# every step of the cache run, with what the simulation needs
R = {}
for d in glob.glob(f"{sc}/*/*__g*"):
    task, k = os.path.basename(d).split("__g")
    k = int(k)
    tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")]
    ch = [json.loads(l) for l in open(d.replace(sc, rec) + "/chat.jsonl")]
    steps = []
    for i, s in enumerate(tr):
        t = (ch[i].get("t") or {}) if i < len(ch) else {}
        hit = s.get("skipped") == "scache"
        steps.append(dict(key=action_key(json.loads(s["action"]), s.get("a11y_hit")), hit=hit, ts=ts(s),
                          e=bg.get((task, k, i + 1), 0.0) if hit else s["exec_s"],
                          think=t.get("llm_end", 0) - t.get("llm_start", 0),
                          scr=screen(ch[i]) if i < len(ch) else None))
    R[(task, k)] = steps

# the cache's (screen, action) pairs: warm traces + this epoch's steps once run (by recording time; approximate)
cache_warm, cache_cur = set(), {}
for d in (p for x in glob.glob("/mnt/ssd2/vikranth/osworld/traces/*_shot") for p in glob.glob(f"{x}/*/*__g*")):
    if "rec128e2_shot" in d or "rec128e3_shot" in d or not os.path.exists(f"{d}/chat.jsonl"):
        continue
    task = os.path.basename(d).split("__g")[0]
    ch = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
    tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")] if os.path.exists(f"{d}/traj.jsonl") else []
    for j in range(min(len(ch), len(tr)) - 1):
        cache_warm.add((task, screen(ch[j]), action_key(json.loads(tr[j]["action"]), tr[j].get("a11y_hit"))))
for (task, k), steps in R.items():
    for s in steps:
        cache_cur.setdefault((task, s["scr"], s["key"]), s["ts"])
in_cache = lambda task, scr, key, at: (task, scr, key) in cache_warm or cache_cur.get((task, scr, key), 1e18) < at


def guesses_for():
    """TAGE warmed on `warm`, then fed epoch 2 in time order. -> {(task, k, i): ranked guesses for step i}"""
    tage = OnlineTage(8)
    tage.warm(warm)
    order = sorted((s["ts"], task, k, i) for (task, k), steps in R.items() for i, s in enumerate(steps))
    hist, out = defaultdict(list), {}
    for _, task, k, i in order:
        s = R[(task, k)][i]
        if s["key"] is not None:
            tage.tage.update(task, hist[(task, k)], s["key"])
            hist[(task, k)].append(s["key"])
            out[(task, k, i + 1)] = tage.tage.predict(task, hist[(task, k)])[0]  # the copy's guess for step i+1
    return out


G = guesses_for()


def run(rule, topk=1, tail=False, skip_cached=False):
    saved, forks, wins, cand = {}, 0, 0, 0
    for (task, k), steps in R.items():
        sv = 0.0
        for i in range(1, len(steps)):
            prev, cur = steps[i - 1], steps[i]
            if rule == "v1" and prev["hit"]:
                continue  # v1: no pre-fork at a hit step
            if tail and sum(1 for x in ends_sorted if x > prev["ts"] - t0) > 32:
                continue
            g = G.get((task, k, i), [])[:topk]
            if skip_cached and prev["hit"] and g and in_cache(task, cur["scr"], g[0], prev["ts"]):
                continue  # the cache will serve the guessed step: no fork
            forks += len(g) if g else 0
            if cur["hit"] or cur["key"] is None:
                continue  # nothing to save (the cache serves it / done)
            cand += 1
            if cur["key"] not in g:
                continue
            wins += 1
            e0, e1, t = prev["e"], cur["e"], cur["think"]
            sv += min(e1, t) if not prev["hit"] else max(t, e0) + e1 - max(t, e0 + e1)
        saved[(task, k)] = sv
    new = sorted(end[r] - saved.get(r, 0.0) for r in end)
    base = ends_sorted
    return dict(epoch=new[-1] / 60, p99=new[int(len(new) * .99) - 1] / 60, forks=forks, misses=cand, wins=wins,
                saved_min=sum(saved.values()) / 60), base


print(f"cache run {sc}: epoch {ends_sorted[-1] / 60:.2f} min, 99% {ends_sorted[int(len(ends_sorted) * .99) - 1] / 60:.2f}; "
      f"steps {sum(len(v) for v in R.values())}, misses {sum(1 for v in R.values() for s in v if not s['hit'])}")
# the oracle: every miss after a step with a pre-fork guessed right (keep rule, any guess)
for name, kw in [("v1 (what ran)", dict(rule="v1")), ("keep, top-1", dict(rule="keep")), ("keep, top-2", dict(rule="keep", topk=2)),
                 ("keep, top-1, skip cached", dict(rule="keep", skip_cached=True)),
                 ("keep, top-2, skip cached", dict(rule="keep", topk=2, skip_cached=True)),
                 ("keep, top-2, skip cached, tail", dict(rule="keep", topk=2, skip_cached=True, tail=True)),
                 ("keep, top-8 (near-oracle)", dict(rule="keep", topk=8))]:
    r, base = run(**kw)
    print(f"{name:32s} epoch {r['epoch']:5.2f} ({r['epoch'] / (base[-1] / 60) - 1:+.1%} vs cache) | 99% {r['p99']:5.2f} | "
          f"forks {r['forks']:4d} | misses covered {r['misses']:4d}, right guess {r['wins']:3d} | env saved {r['saved_min']:.1f} rollout-min")
last = max(end, key=end.get)
print("last rollout", last, f"ends {end[last] / 60:.2f}; its misses:",
      [(i + 1, round(s["e"]), "hit-before" if i and R[last][i - 1]["hit"] else "", (G.get((last[0], last[1], i)) or [None])[:2] == [] or s["key"] in (G.get((last[0], last[1], i)) or [])[:2])
       for i, s in enumerate(R[last]) if not s["hit"] and s["key"]])
