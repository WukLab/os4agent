"""Offline, realistic version of think_stream_sim.py: at a point f of the streaming thinking (0.25, 0.5, ...), guess the
element on the screen that the thinking named most recently; speculate that the action targets it. Scored on the
screen cache run's misses: right if it is the final action's target element.

  python3 think_stream_real.py SC_RUN RECORDING

A guess at f saves min(e, (1 - f) * t) when right (the copy runs it while the model keeps thinking); a wrong guess costs
a fork. Also reported: 'stable' -- guess only once the most-recent element has not changed for the last 10% of text.
"""
import glob, json, os, sys

sc, rec = sys.argv[1], sys.argv[2]
ev = [json.loads(l) for l in open(f"{sc}/events.jsonl")]
t0 = ev[0]["t"]
end = {(e["task"], e["k"]): e["t"] - t0 for e in ev if e["event"] == "rollout_done"}
STEPS = []
for d in glob.glob(f"{sc}/*/*__g*"):
    task, k = os.path.basename(d).split("__g")
    tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")]
    ch = [json.loads(l) for l in open(d.replace(sc, rec) + "/chat.jsonl")]
    for i, s in enumerate(tr):
        if s.get("skipped") == "scache" or i >= len(ch):
            continue
        act = json.loads(s["action"])
        tid = act.get("id", act.get("from"))
        rows = ch[i].get("rows") or []
        if not isinstance(tid, int) or not (0 <= tid < len(rows)):
            continue  # keyboard / type / done actions: no element to guess
        resp = ch[i].get("response") or ""
        think = (resp.split("</think>")[0] if "</think>" in resp else resp.rsplit("Action:", 1)[0]).lower()
        names = {}
        for j, r in enumerate(rows):  # element name -> row ids (names that are too short or shared are ambiguous)
            n = (r[1] or "").strip().lower()
            if len(n) >= 4:
                names.setdefault(n, []).append(j)
        t = (ch[i].get("t") or {})
        STEPS.append(dict(r=(task, int(k)), e=s["exec_s"], t=t.get("llm_end", 0) - t.get("llm_start", 0),
                          truth=(rows[tid][1] or "").strip().lower(), think=think, names=names))


def latest(think, names, upto):
    """The element name whose latest mention in think[:upto] ends last (longest name wins ties)."""
    best, at = None, -1
    for n in names:
        p = think.rfind(n, 0, upto)
        if p >= 0 and (p + len(n) > at or (p + len(n) == at and len(n) > len(best))):
            best, at = n, p + len(n)
    return best, at


def score(f, stable=False):
    right = guessed = 0
    saved = {}
    for s in STEPS:
        L = len(s["think"])
        g, at = latest(s["think"], s["names"], int(f * L))
        if g is None:
            continue
        if stable and latest(s["think"], s["names"], int(max(0.0, f - 0.1) * L))[0] != g:
            continue  # still changing its mind
        guessed += 1
        if g == s["truth"]:
            right += 1
            saved[s["r"]] = saved.get(s["r"], 0.0) + min(s["e"], (1 - f) * s["t"])
    base = sorted(end.values())
    new = sorted(end[r] - saved.get(r, 0.0) for r in end)
    return guessed, right, new[-1] / 60, base[-1] / 60, new[int(len(new) * .99) - 1] / 60, sum(saved.values()) / 60


print(f"cache misses that target a screen element: {len(STEPS)}")
for f in (0.25, 0.5, 0.75, 0.9):
    for stable in (False, True):
        g, r, ep, b, p99, sv = score(f, stable)
        print(f"guess at {f:.0%} of the thinking{' (stable)' if stable else '         '}: guessed {g:3d}, right {r:3d} "
              f"({r / max(1, g):.0%} of guesses, {r / len(STEPS):.0%} of misses) | epoch {b:.2f} -> {ep:.2f} "
              f"({ep / b - 1:+.1%}) | 99% {p99:.2f} | env saved {sv:.1f} rollout-min")
