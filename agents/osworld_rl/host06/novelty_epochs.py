"""How much of each epoch is new: steps whose screen / (screen, action) / action history never occurred before, in
any earlier epoch or earlier in the same epoch (recorded time order). The cache can't hit a new (screen, action);
TAGE can't hit an action it never saw after that history.

  python3 novelty_epochs.py EPOCH1_DIR EPOCH2_DIR ...
"""
import glob, hashlib, json, os, re, sys

sys.path[:0] = ["/mnt/ssd2/vikranth/osworld"]
from toolspec.keys import action_key  # noqa: E402

CLOCK = re.compile(r"\b\d{1,2}:\d{2}( [AP]M)?\b")


def screen(c):
    m = (c.get("messages") or [{}])[-1].get("content")
    if not m:
        return None
    m = m[-1]["text"] if isinstance(m, list) else m
    if "Accessibility tree:\n" not in m:
        return None
    return hashlib.sha1(CLOCK.sub("", m.split("Accessibility tree:\n", 1)[1].rsplit("\n\nNext action?", 1)[0]).encode()).hexdigest()


def steps(root):
    out = []
    for d in glob.glob(os.path.join(root, "*", "*__g*")):
        if not (os.path.exists(f"{d}/chat.jsonl") and os.path.exists(f"{d}/traj.jsonl")):
            continue
        task = os.path.basename(d).split("__g")[0]
        ch = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
        tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")]
        hist = []
        for j in range(min(len(ch), len(tr))):
            a = action_key(json.loads(tr[j]["action"]), tr[j].get("a11y_hit"))
            s = screen(ch[j])
            if a is None or s is None:
                continue
            out.append((ch[j]["t"]["llm_end"], j + 1, task, s, a, tuple(hist[-3:])))
            hist.append(a)
    return sorted(out)


seen_s, seen_sa, seen_ha = set(), set(), set()
print(f"{'epoch':6s} {'steps':>6s} {'new screen':>11s} {'new (screen,action)':>20s} {'new action after last-3 history':>32s} "
      f"{'tasks':>6s} {'distinct screens':>17s}")
for e, root in enumerate(sys.argv[1:], 1):
    st = steps(root)
    ns = nsa = nha = 0
    screens = set()
    for _, _, task, s, a, h in st:
        ns += (task, s) not in seen_s
        nsa += (task, s, a) not in seen_sa
        nha += (task, h, a) not in seen_ha
        seen_s.add((task, s))
        seen_sa.add((task, s, a))
        seen_ha.add((task, h, a))
        screens.add((task, s))
    n = len(st)
    print(f"{e:<6d} {n:6d} {ns / n:11.1%} {nsa / n:20.1%} {nha / n:32.1%} {len({x[2] for x in st}):6d} {len(screens):17d}")
