"""Offline: prefix_cache_weaker = the screen cache serves a hit only if the screenshot matches too (not just the
accessibility tree). Measured on a finished --screen-cache run (each hit's check outcome is known).

  venv/bin/python weaker_sim.py SC_RUN RECORDING

For every hit of the cache run: the entries it could have come from (same task, tree, action, available by then:
earlier traces, or a step of this epoch that already ran), and whether any of them was recorded on the same screenshot.
  bytes : PNG files identical
  pixels: decoded images identical
  mask  : identical except the taskbar clock corner (it changes every minute)
A hit the weaker cache refuses runs normally instead: its env time (the background run's) goes back on the critical
path; if the hit had been rejected, the repeated model call it cost is saved. Replays have fixed model times, so each
rollout ends earlier/later by exactly that; the epoch is the last rollout.
"""
import datetime as dt, glob, hashlib, io, json, os, re, sys
from PIL import Image

sys.path[:0] = ["/mnt/ssd2/vikranth/osworld"]
from toolspec.keys import action_key  # noqa: E402

sc, rec = sys.argv[1], sys.argv[2]
T = "/mnt/ssd2/vikranth/osworld/traces"
CLOCK = re.compile(r"\b\d{1,2}:\d{2}( [AP]M)?\b")
ts = lambda s: dt.datetime.strptime(s["action_timestamp"], "%Y%m%d@%H%M%S%f").timestamp()


def tree(c):
    m = (c.get("messages") or [{}])[-1].get("content")
    if not m:
        return None
    m = m[-1]["text"] if isinstance(m, list) else m
    if "Accessibility tree:\n" not in m:
        return None
    return hashlib.sha1(CLOCK.sub("", m.split("Accessibility tree:\n", 1)[1].rsplit("\n\nNext action?", 1)[0]).encode()).hexdigest()


_cache = {}


def sig(path, mode):
    """Signature of a screenshot under a matching mode (None if missing)."""
    if not path or not os.path.exists(path):
        return None
    k = (path, mode)
    if k not in _cache:
        if mode == "bytes":
            _cache[k] = hashlib.sha1(open(path, "rb").read()).hexdigest()
        else:
            im = Image.open(path).convert("RGB")
            if mode == "mask":  # blank the bottom-right taskbar corner where the clock sits
                w, h = im.size
                im.paste((0, 0, 0), (int(w * 0.88), int(h * 0.94), w, h))
            _cache[k] = hashlib.sha1(im.tobytes()).hexdigest()
    return _cache[k]


# observations: (task, tree before, action) -> [(available at, screenshot before)]
obs = {}


def add(task, d, ch, tr, avail_of):
    for j in range(min(len(ch), len(tr)) - 1):
        t = tree(ch[j])
        if t is None or j == 0:  # step 0's screenshot is not saved
            continue
        key = (task, t, action_key(json.loads(tr[j]["action"]), tr[j].get("a11y_hit")))
        obs.setdefault(key, []).append((avail_of(j), f"{d}/step_{j}.png"))


for x in glob.glob(f"{T}/*_shot"):
    if os.path.basename(x) in ("rec128e2_shot", "rec128e3_shot"):
        continue
    for d in glob.glob(f"{x}/*/*__g*"):
        if os.path.exists(f"{d}/chat.jsonl") and os.path.exists(f"{d}/traj.jsonl"):
            add(os.path.basename(d).split("__g")[0], d, [json.loads(l) for l in open(f"{d}/chat.jsonl")],
                [json.loads(l) for l in open(f"{d}/traj.jsonl")], lambda j: -1e18)

ev = [json.loads(l) for l in open(f"{sc}/events.jsonl")]
t0 = ev[0]["t"]
end = {(e["task"], e["k"]): e["t"] - t0 for e in ev if e["event"] == "rollout_done"}
chk = {(e["task"], e["k"], e["step"]): e for e in ev if e["event"] == "scache_check"}
HITS = []
for d in glob.glob(f"{sc}/*/*__g*"):
    task, k = os.path.basename(d).split("__g")
    k = int(k)
    tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")]
    rd = d.replace(sc, rec)
    ch = [json.loads(l) for l in open(f"{rd}/chat.jsonl")]
    stamps = [ts(s) for s in tr]
    # this epoch's steps become entries once they have run (miss: its action ts + exec; hit: + its background run)
    add(task, rd, ch, tr, lambda j: stamps[j] + (tr[j]["exec_s"] if tr[j].get("skipped") != "scache"
                                                   else chk.get((task, k, j + 1), {}).get("bg_s", 0.0)))
    for i, s in enumerate(tr):
        if s.get("skipped") != "scache" or i == 0 or i >= len(ch):
            continue
        c = chk.get((task, k, i + 1))
        if c is None:
            continue
        nxt = stamps[i + 1] if i + 1 < len(stamps) else None
        llm = (ch[i + 1].get("t") or {}) if i + 1 < len(ch) else {}
        redo = max(0.0, (nxt - stamps[i]) - s["exec_s"] - (llm.get("llm_end", 0) - llm.get("llm_start", 0))) if nxt else 0.0
        HITS.append(dict(r=(task, k), at=stamps[i], ok=c["ok"], bg=c["bg_s"], redo=redo,
                         key=(task, tree(ch[i]), action_key(json.loads(s["action"]), s.get("a11y_hit"))),
                         shot=f"{rd}/step_{i}.png"))

print(f"cache run {sc}: epoch {max(end.values()) / 60:.2f} min; hits checked {len(HITS)}, rejected "
      f"{sum(not h['ok'] for h in HITS)} (each cost a repeated model call, median "
      f"{sorted(h['redo'] for h in HITS if not h['ok'])[sum(not h['ok'] for h in HITS) // 2]:.0f} s)")
base = sorted(end.values())
for mode in ("tree only (as run)", "bytes", "pixels", "mask"):
    keep = drop_ok = drop_rej = keep_rej = 0
    delta = {}
    for h in HITS:
        if mode.startswith("tree"):
            kept = True
        else:
            me = sig(h["shot"], mode)
            kept = me is not None and any(a < h["at"] and sig(p, mode) == me for a, p in obs.get(h["key"], []))
        if kept:
            keep += 1
            keep_rej += not h["ok"]
            continue
        # refused: the step runs normally (+ its env time); a rejected hit's repeated model call is saved
        delta[h["r"]] = delta.get(h["r"], 0.0) + h["bg"] - (h["redo"] if not h["ok"] else 0.0)
        drop_ok += h["ok"]
        drop_rej += not h["ok"]
    new = sorted(end[r] + delta.get(r, 0.0) for r in end)
    print(f"{mode:20s}: served {keep:4d} hits ({keep_rej} rejected, {keep_rej / max(1, keep):.0%}) | refused {drop_ok + drop_rej:4d} "
          f"({drop_rej} would have been rejected) | epoch {new[-1] / 60:.2f} min ({new[-1] / base[-1] - 1:+.1%} vs cache run) | "
          f"99% {new[int(len(new) * .99) - 1] / 60:.2f}")
