"""Offline 16x8 epoch with in-place speculation once fewer than BELOW rollouts are live. Rollouts = a recorded run's
rollouts cycled to 8 per task (per-step model W and env E as recorded), all starting at t=0. TAGE (warmed) guesses each
step in global time order; a top-1 hit at step >= 3 saves min(E, W - D); a miss costs max(0, B - W).
Usage: spec_sim128.py <run> <warm,dirs> <below> [D B]"""
import json, glob, os, sys, heapq
sys.path.insert(0, "/mnt/ssd2/vikranth/osworld")
from toolspec.online import OnlineTage, web_step
run, warm, BELOW = sys.argv[1], sys.argv[2].split(","), int(sys.argv[3])
D, B = (float(sys.argv[4]), float(sys.argv[5])) if len(sys.argv) > 5 else (3.0, 10.3)
rec = {}
for run in run.split("+"):
  bad = {(e["task"], e["k"]) for e in map(json.loads, open(f"traces/{run}/events.jsonl")) if e["event"] == "rollout_done" and e.get("error")}
  over = set()
  for d in glob.glob(f"traces/{run}/*/*__g*"):
    task, k = os.path.basename(d).split("__g")
    if (task, int(k)) in bad: continue
    chat = [json.loads(l) for l in open(d + "/chat.jsonl")]
    st = [(s, chat[i]["t"]["llm_end"] - chat[i]["t"]["llm_start"], s["exec_s"])
          for i, s in enumerate(json.loads(l) for l in open(d + "/traj.jsonl") if l.strip()) if i < len(chat) and chat[i].get("t") and "exec_s" in s]
    if task not in over: rec[task] = []; over.add(task)
    rec[task].append((d, st))
SET = os.environ.get("SET")
if SET:  # task list file; tasks without traces borrow a stand-in task's rollouts ("new=standin,...")
    want = [t for v in json.load(open(SET)).values() for t in v]
    sub = dict(x.split("=") for x in os.environ.get("SUB", "").split(",") if x)
    full = lambda p: next(k for k in rec if k.startswith(p))
    rec = {t: rec[t] if t in rec else rec[full(sub[t[:8]])] for t in want}
EXT = int(os.environ.get("EXT", 0))  # extend unsolved cap-hitters to EXT steps by repeating their last 8 steps
if EXT:
    for t in rec:
        rec[t] = [(d, st + [st[len(st) - 8 + (j % 8)] for j in range(EXT - len(st))]) if len(st) >= 15 else (d, st) for d, st in rec[t]]
rolls = [(t, i, rec[t][i % len(rec[t])]) for t in rec for i in range(8)]
SLOTS, LO_ONLY = int(os.environ.get("SLOTS", 10**6)), os.environ.get("LO_ONLY", "0") == "1"
WAVE = float(os.environ.get("WAVE", 1))
MED = os.environ.get("MED", "0") == "1"  # speculate if prev env time >= running median env time
ENVB = os.environ.get("ENVB", "0") == "1"  # speculate only if the previous step had env > model
def epoch(spec):
    T = OnlineTage(topk=2); T.warm([f"traces/{w}" for w in warm])
    heap = [(0.0, r, 0) for r in range(len(rolls))]  # (time the next step starts, rollout, step index)
    live, done_t, hits, n_spec, saved, busy, peak = len(rolls), [], 0, 0, 0.0, [], 0
    seen = []
    while heap:
        t, r, i = heapq.heappop(heap)
        task, rep, (d, st) = rolls[r]
        if i >= len(st):
            live -= 1; done_t.append(t); continue
        s, w, e = st[i]
        if live > len(rolls) // 2: w = w * WAVE
        rid = f"{d}#{rep}"
        T.decide(task, rid); _, key = web_step(d, s); out = T.reveal_key(task, rid, key)
        dt = w + e
        busy = [b for b in busy if b > t]
        lo = "libreoffice" in d
        med_ok = i > 0 and bool(seen) and st[i - 1][2] >= sorted(seen)[len(seen) // 2]
        seen.append(e)
        envb = i > 0 and st[i - 1][2] > st[i - 1][1] * (WAVE if live > len(rolls) // 2 else 1)
        if spec and live < BELOW and s.get("step_num", 0) >= 3 and key is not None and len(busy) < SLOTS and (lo or not LO_ONLY) and (envb or not ENVB) and (med_ok or not MED):
            busy.append(t + w); peak = max(peak, len(busy))
            n_spec += 1
            if out and out["hit1"]: hits += 1; g = min(e, max(0.0, w - D)); dt -= g; saved += g
            else: dt += max(0.0, B - w); saved -= max(0.0, B - w)
        heapq.heappush(heap, (t + dt, r, i + 1))
    done_t.sort()
    epoch.peak = peak
    return done_t, hits, n_spec, saved
base, *_ = epoch(False); new, hits, n_spec, saved = epoch(True)
n = len(base)
def tail(d, live): return 100 * (d[-1] - d[n - live - 1]) / d[-1]
print(f"{n} rollouts ({len(rec)} tasks x 8), speculate when < {BELOW} live, D={D} B={B}")
print(f"  speculated steps {n_spec}, top-1 hits {hits} ({100*hits/max(n_spec,1):.0f}%), env time saved {saved/60:.1f} min")
for name, d in (("baseline", base), ("spec", new)):
    print(f"  {name:8}: epoch {d[-1]/60:5.1f} min | <64 live {tail(d,64):3.0f}%  <32 live {tail(d,32):3.0f}%  <16 live {tail(d,16):3.0f}%")
print(f"  peak concurrent backups {epoch.peak}")
print(f"  epoch change {100*(new[-1]-base[-1])/base[-1]:+.1f}%")
