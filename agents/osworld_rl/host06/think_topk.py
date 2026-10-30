"""think_stream_real.py with top-k guesses: at point f of the thinking, fork one copy per guess.
Rankers: recent = the k elements named most recently; intent = elements named right after an intent phrase
("click", "select", "press", "open", "choose", "use the", "go to") first, then by recency.
  python3 think_topk.py SC_RUN RECORDING"""
import re, sys
sys.argv = sys.argv[:3]
exec(open("/mnt/ssd2/vikranth/osworld/think_stream_real.py").read().split("def latest")[0])
INTENT = re.compile(r"(click(?:ing)?(?: on)?|select(?:ing)?|press(?:ing)?|open(?:ing)?|choos(?:e|ing)|use the|go to|tap)\s+(?:the\s+)?[\"'\[]?$")


def ranked(think, names, upto, how):
    m = []
    for n in names:
        p = think.rfind(n, 0, upto)
        if p >= 0:
            intent = bool(INTENT.search(think[max(0, p - 40):p]))
            m.append(((intent if how == "intent" else 0), p + len(n), len(n), n))
    return [x[-1] for x in sorted(m, reverse=True)]


def score(f, k, how):
    right = forks = 0
    saved = {}
    for s in STEPS:
        g = ranked(s["think"], s["names"], int(f * len(s["think"])), how)[:k]
        forks += len(g)
        if s["truth"] in g:
            right += 1
            saved[s["r"]] = saved.get(s["r"], 0.0) + min(s["e"], (1 - f) * s["t"])
    base = sorted(end.values())
    new = sorted(end[r] - saved.get(r, 0.0) for r in end)
    last = max(end, key=end.get)
    return right, forks, new[-1] / 60, base[-1] / 60, new[int(len(new) * .99) - 1] / 60, saved.get(last, 0.0)


print(f"cache misses that target a screen element: {len(STEPS)} (cache run epoch {max(end.values()) / 60:.2f} min, 99% 15.47)")
for how in ("recent", "intent"):
    for k in (1, 3, 5):
        for f in (0.25, 0.5):
            r, fk, ep, b, p99, sl = score(f, k, how)
            print(f"{how:6s} top-{k} at {f:.0%}: right {r:3d}/{len(STEPS)} ({r / len(STEPS):.0%}), forks {fk:4d} | "
                  f"epoch {ep:.2f} ({ep / b - 1:+.1%}) | 99% {p99:.2f} | slowest rollout saves {sl:.0f} s")
