"""Cache key variants per GRPO epoch (all earlier epochs as knowledge, plus this epoch online).

  python3 cache_keys.py EPOCH1_DIR EPOCH2_DIR ...

keys: screen         = (task, screen, action)                     -- the prefix (screen) cache
      last-k actions = (task, the k previous actions, action), k = 1, 2, 3
      full history   = (task, every action so far, action)        -- the action-only cache
Per step: hit = key cached; right = the cached next screen is the real one (a wrong hit is rejected by the check).
Entries keep the latest real result.
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


def steps(root):
    out = []
    for d in glob.glob(os.path.join(root, "*", "*__g*")):
        if not (os.path.exists(f"{d}/chat.jsonl") and os.path.exists(f"{d}/traj.jsonl")):
            continue
        task = os.path.basename(d).split("__g")[0]
        ch = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
        tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")]
        hist = []
        for j in range(min(len(ch), len(tr)) - 1):
            a = action_key(json.loads(tr[j]["action"]), tr[j].get("a11y_hit"))
            s, nxt = screen(ch[j]), screen(ch[j + 1])
            if a is None or s is None or nxt is None:
                continue
            out.append(dict(used=ch[j]["t"]["llm_end"], avail=ch[j + 1]["t"]["obs"], task=task, s=s, a=a, h=tuple(hist), nxt=nxt))
            hist.append(a)
    return out


KEYS = {"screen": lambda x: (x["task"], x["s"], x["a"]),
        "last-1 action": lambda x: (x["task"], x["h"][-1:], x["a"]),
        "last-2 actions": lambda x: (x["task"], x["h"][-2:], x["a"]),
        "last-3 actions": lambda x: (x["task"], x["h"][-3:], x["a"]),
        "full history": lambda x: (x["task"], x["h"], x["a"])}
data = [steps(r) for r in epochs]
print(f"{'key':16s} " + " ".join(f"{'epoch ' + str(e):>16s}" for e in range(1, len(epochs) + 1)) + "   (right %, hit % in brackets)")
for name, kf in KEYS.items():
    cells = []
    for e in range(len(epochs)):
        cache = {}
        for w in data[:e]:  # earlier epochs, in time order: latest result wins
            for x in sorted(w, key=lambda x: x["avail"]):
                cache[kf(x)] = x["nxt"]
        own = defaultdict(list)
        for x in data[e]:
            own[kf(x)].append((x["avail"], x["nxt"]))
        n = hit = right = 0
        for x in data[e]:
            k = kf(x)
            prior = [p for p in own.get(k, []) if p[0] <= x["used"]]
            ref = max(prior)[1] if prior else cache.get(k)
            n += 1
            if ref is not None:
                hit += 1
                right += ref == x["nxt"]
        cells.append(f"{right / n:6.1%} ({hit / n:5.1%})")
    print(f"{name:16s} " + " ".join(f"{c:>16s}" for c in cells))
