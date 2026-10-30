"""Screen-cache hit rate and correctness per GRPO epoch (offline, from the recordings' chat.jsonl + traj.jsonl).

  python3 cache_epochs.py EPOCH1_DIR EPOCH2_DIR EPOCH3_DIR ...

Key = (task, accessibility tree with the clock masked, action key), as --screen-cache. For epoch e the cache holds the
warm epochs' steps, plus each step of epoch e once it has run (its next screen exists, recorded time). Per step:
hit = key in the cache; right = the cached next screen equals the one the desktop produced (a wrong hit is rejected
by the check in a run and costs a repeated model call). Warm sets: none (cold), previous epoch only, all earlier.
"""
import glob, hashlib, json, os, re, sys
from collections import defaultdict

sys.path[:0] = ["/mnt/ssd2/vikranth/osworld"]
from toolspec.keys import action_key  # noqa: E402

CLOCK = re.compile(r"\b\d{1,2}:\d{2}( [AP]M)?\b")
epochs = sys.argv[1:]


def screen(c):
    m = (c.get("messages") or [{}])[-1].get("content")
    if not m:
        return None
    m = m[-1]["text"] if isinstance(m, list) else m
    if "Accessibility tree:\n" not in m:
        return None
    return hashlib.sha1(CLOCK.sub("", m.split("Accessibility tree:\n", 1)[1].rsplit("\n\nNext action?", 1)[0]).encode()).hexdigest()


def steps_of(root):
    """[(available at, used at, step, key, next screen)] for every step with a next screen"""
    out = []
    for d in glob.glob(os.path.join(root, "*", "*__g*")):
        if not (os.path.exists(f"{d}/chat.jsonl") and os.path.exists(f"{d}/traj.jsonl")):
            continue
        task = os.path.basename(d).split("__g")[0]
        ch = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
        tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")]
        for j in range(min(len(ch), len(tr)) - 1):
            a = action_key(json.loads(tr[j]["action"]), tr[j].get("a11y_hit"))
            s, nxt = screen(ch[j]), screen(ch[j + 1])
            if a is None or s is None or nxt is None:
                continue
            used = ch[j]["t"]["llm_end"]  # the action is known here: the lookup
            avail = ch[j + 1]["t"]["obs"]  # its next screen exists here: the entry
            out.append((avail, used, j + 1, (task, s, a), nxt))
    return out


def score(warm, cur):
    cache = {}
    for w in warm:
        for _, _, _, k, nxt in steps_of(w):
            cache.setdefault(k, nxt)
    own = defaultdict(list)
    cur_steps = steps_of(cur)
    for avail, _, _, k, nxt in cur_steps:
        own[k].append((avail, nxt))
    n = hit = right = 0
    by = defaultdict(lambda: [0, 0, 0])
    for _, used, step, k, nxt in cur_steps:
        if k in cache:
            ref = cache[k]
        else:
            prior = [x for x in own.get(k, []) if x[0] <= used]
            ref = max(prior)[1] if prior else None  # latest real result wins
        n += 1
        b = "1-3" if step <= 3 else "4-10" if step <= 10 else "11-20"
        by[b][0] += 1
        if ref is not None:
            hit += 1
            right += ref == nxt
            by[b][1] += 1
            by[b][2] += ref == nxt
    return n, hit / n, right / n, right / max(1, hit), {b: (v[1] / v[0], v[2] / v[0]) for b, v in by.items()}


print(f"{'epoch':8s} {'warmed on':28s} {'steps':>6s} {'hit':>6s} {'right':>6s} {'right/hit':>9s}   right by step: 1-3 / 4-10 / 11-20")
for e, cur in enumerate(epochs, 1):
    sets = [("none (cold)", [])]
    if e >= 2:
        sets.append(("previous epoch only", [epochs[e - 2]]))
    if e >= 3:
        sets.append((f"all earlier (epochs 1-{e - 1})", epochs[:e - 1]))
    for name, warm in sets:
        n, h, r, rh, by = score(warm, cur)
        print(f"epoch {e}  {name:28s} {n:6d} {h:6.1%} {r:6.1%} {rh:9.1%}   "
              f"{by.get('1-3', (0, 0))[1]:.0%} / {by.get('4-10', (0, 0))[1]:.0%} / {by.get('11-20', (0, 0))[1]:.0%}")
