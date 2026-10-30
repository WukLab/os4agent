"""Offline: cache (screen or action-history key) x pre-fork speculation, on one recorded epoch.

  venv/bin/python combo2_sim.py PREV_EPOCH CUR_EPOCH

Per rollout, the recorded model time t_i and env time e_i of each step (replays use the recorded model times, so a
rollout's timeline is exact up to env-time savings). Cache (eager, as --screen-cache): a hit returns the cached next
screen at once and the desktop runs the action in the background; a hit is used only if the cached next screen equals
the real one (else it is a miss: the check rejects it). Keys: screen = (task, screen, action); actions = (task, exact
action history). Warm: the previous epoch; entries of this epoch once a rollout has really run them.
Speculation (pre-fork, P2): while the model thinks about action i-1 a copy is forked; once i-1 is known the copy runs it,
then TAGE's guess for i. If the guess is right, step i is adopted from the copy: done at max(decision i, copy ready)
instead of after e_i. 'keep': a pre-fork is also made at a cache-hit step (the copy runs the hit action itself).
"""
import glob, hashlib, json, os, re, sys
from collections import defaultdict

sys.path[:0] = ["/mnt/ssd2/vikranth/osworld"]
from toolspec.keys import action_key  # noqa: E402
from toolspec.online import OnlineTage  # noqa: E402

prev_dir, cur_dir = sys.argv[1], sys.argv[2]
CLOCK = re.compile(r"\b\d{1,2}:\d{2}( [AP]M)?\b")
HIT_S = 0.2


def tree(c):
    m = (c.get("messages") or [{}])[-1].get("content")
    if not m:
        return None
    m = m[-1]["text"] if isinstance(m, list) else m
    return hashlib.sha1(CLOCK.sub("", m.split("Accessibility tree:\n", 1)[-1].rsplit("\n\nNext action?", 1)[0]).encode()).hexdigest()


def load(root):
    out = []
    for d in glob.glob(f"{root}/*/*__g*"):
        if not os.path.exists(f"{d}/timing.json"):
            continue
        task, k = os.path.basename(d).split("__g")
        ch = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
        tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")]
        tm = json.load(open(f"{d}/timing.json"))
        if not tm.get("t_eval") or len(ch) != len(tr):
            out.append(dict(task=task, k=int(k), start=tm["t_start"], steps=None, end=tm["t_end"]))
            continue
        steps = []
        for i, (c, s) in enumerate(zip(ch, tr)):
            steps.append(dict(key=action_key(json.loads(s["action"]), s.get("a11y_hit")), t=c["t"]["llm_end"] - c["t"]["obs"],
                              e=s["exec_s"], tree=tree(c), avail=ch[i + 1]["t"]["obs"] if i + 1 < len(ch) else tm["t_eval"]))
        for i, s in enumerate(steps):
            s["next"] = steps[i + 1]["tree"] if i + 1 < len(steps) else None
        out.append(dict(task=task, k=int(k), start=tm["t_start"], pre=ch[0]["t"]["obs"] - tm["t_start"], steps=steps,
                        end=tm["t_eval"], post=tm["t_end"] - tm["t_eval"]))
    return out


prev, cur = load(prev_dir), load(cur_dir)
t0 = min(r["start"] for r in cur)


def ckey(mode, r, i, hist):
    s = r["steps"][i]
    return (r["task"], s["tree"], s["key"]) if mode == "screen" else (r["task"], tuple(hist + [s["key"]]))


def build(mode):
    """previous-epoch entries (key -> next screen) and this epoch's (key -> [(available at, next screen)])"""
    old, new = {}, defaultdict(list)
    for src, dst in ((prev, None), (cur, new)):
        for r in src:
            if not r["steps"]:
                continue
            hist = []
            for i, s in enumerate(r["steps"]):
                if s["key"] is None:
                    break
                k = ckey(mode, r, i, hist)
                if dst is None:
                    old.setdefault(k, s["next"])
                else:
                    dst[k].append((s["avail"], s["next"]))
                hist.append(s["key"])
    return old, new


# TAGE guesses for each step i of each rollout: warmed on the previous epoch, then fed this epoch in recorded order
tage = OnlineTage(8)
tage.warm([prev_dir])
order = sorted((r["start"] + r["pre"] + sum(x["t"] + x["e"] for x in r["steps"][:i]), id(r), i, r)
               for r in cur if r["steps"] for i in range(len(r["steps"])))
GUESS, hists = {}, defaultdict(list)
for _, _, i, r in order:
    s = r["steps"][i]
    if s["key"] is None:
        continue
    tage.tage.update(r["task"], hists[id(r)], s["key"])
    hists[id(r)].append(s["key"])
    g = tage.tage.predict(r["task"], hists[id(r)])[0]
    GUESS[(id(r), i + 1)] = g[0] if g else None


def sim(r, cache, spec, keep=True):
    if not r["steps"]:
        return r["end"] - r["start"]
    old, new = cache if cache else ({}, {})
    now, worker, hist = r["pre"], r["pre"], []
    dec_prev, kind_prev, e_prev = None, None, 0.0  # decision time / kind of the previous step
    for i, s in enumerate(r["steps"]):
        now += s["t"]
        dec = now
        if s["key"] is None:  # done: the desktop must be done with every step before scoring
            now = max(now, worker) + s["e"]
            break
        k = ckey(cache_mode, r, i, hist) if cache else None
        hit = False
        if cache:
            ref = old.get(k, False) if k in old else min(((a, n) for a, n in new.get(k, []) if a <= r["start"] + now),
                                                          default=(None, False))[1]
            hit = ref is not False and (ref is None or s["next"] is None or ref == s["next"])
        if hit:
            worker = max(worker, now) + s["e"]
            now += HIT_S
            kind = "hit"
        else:
            start = max(now, worker)
            adopt = None
            if spec and i >= 2 and dec_prev is not None and (keep or kind_prev != "hit") and GUESS.get((id(r), i)) == s["key"]:
                adopt = dec_prev + e_prev + s["e"]  # the copy ran action i-1 then the guess for i
            now = min(start + s["e"], max(now, adopt)) if adopt is not None else start + s["e"]
            worker = now
            kind = "miss"
        hist.append(s["key"])
        dec_prev, kind_prev, e_prev = dec, kind, s["e"]
    return now + r["post"]


rec_end = sorted(r["end"] - t0 for r in cur)
base = None
print(f"epoch from the recording: {rec_end[-1] / 60:.2f} min")
for name, mode, spec in [("tfork (no cache, no spec)", None, False), ("spec only (P2)", None, True),
                         ("screen cache only", "screen", False), ("action cache only (weaker)", "actions", False),
                         ("screen cache + spec", "screen", True), ("action cache + spec", "actions", True)]:
    cache_mode = mode
    cache = build(mode) if mode else None
    ends = sorted(r["start"] - t0 + sim(r, cache, spec) for r in cur)
    base = base or ends
    print(f"{name:30s} epoch {ends[-1] / 60:5.2f} min ({ends[-1] / base[-1] - 1:+6.1%}) | 99% {ends[int(len(ends) * .99) - 1] / 60:5.2f} "
          f"({ends[int(len(ends) * .99) - 1] / base[int(len(base) * .99) - 1] - 1:+6.1%}) | tail from 16 left "
          f"{(ends[-1] - ends[-17]) / 60:4.2f} min")
