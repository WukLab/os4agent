"""Offline replay of speculative action execution on a GRPO minibatch.   python analyze_gui.py traces/<run> [K=3]
A step is speculated correctly iff the predicted action equals the action the model really issues (then executing it early on
our own VM is equivalent). Prediction uses only siblings (same task, other rollouts) whose step-i action was ISSUED earlier
than ours (causal). Hidden time per hit = min(window, V), window = real-action time - max(sibling action time, our VM ready time).
Action keys: exact code | coarse (40px grid) | elem (a11y element for clicks, else exact code)."""
import collections, datetime, glob, json, os, re, statistics as st, sys
R = sys.argv[1]; K = int(sys.argv[2]) if len(sys.argv) > 2 else 3
ts = lambda s: datetime.datetime.strptime(s, "%Y%m%d@%H%M%S%f").timestamp()
pct = lambda xs, q: sorted(xs)[min(len(xs) - 1, int(len(xs) * q))] if xs else float("nan")
NUM = re.compile(r"-?\d+\.?\d*")
def calls(a): return [l.strip() for l in a.split("\n") if re.match(r"\s*pyautogui\.", l)]
def kind(a):
    if a.strip() in ("DONE", "FAIL", "WAIT"): return a.strip()
    c = calls(a); return re.match(r"pyautogui\.(\w+)", c[0]).group(1) if c else "other"
def exact(s): return " ; ".join(calls(s["action"])) or s["action"].strip()
def coarse(s):
    return re.sub(r"-?\d+\.\d+|-?\d+", lambda m: str(round(float(m.group()) / 40)) if "." in m.group() else m.group(), exact(s)) if kind(s["action"]) in ("click", "doubleClick", "rightClick", "moveTo", "dragTo", "tripleClick") else exact(s)
def elem(s):
    h = s.get("a11y_hit")
    return f"{kind(s['action'])}@{h['key']}" if h and h.get("key") and kind(s["action"]) in ("click", "doubleClick", "rightClick", "tripleClick") else coarse(s)
KEYS = {"exact": exact, "coarse": coarse, "elem": elem}
groups = collections.defaultdict(dict)
for d in glob.glob(f"{R}/results/*/*/*/*/*__g*"):
    m = re.match(r"(.*)__g(\d+)$", os.path.basename(d)); f = f"{d}/traj.jsonl"
    if not os.path.exists(f): continue
    tr = [t for t in map(json.loads, open(f)) if "step_num" in t]
    for t in tr: t["t"] = ts(t["action_timestamp"])
    if tr: groups[m.group(1)][int(m.group(2))] = tr
L = [json.loads(l) for l in open(f"{R}/llm.jsonl")]; llm_p50 = pct([r["t_end"] - r["t_start"] for r in L], .5)
iv = [b["t"] - a["t"] for g in groups.values() for tr in g.values() for a, b in zip(tr, tr[1:])]
V = max(pct(iv, .5) - llm_p50, 0)  # est. VM+harness seconds per step that an early start could hide
steps = sum(len(tr) for g in groups.values() for tr in g.values())
print(f"{len(groups)} groups, {sum(len(g) for g in groups.values())} rollouts, {steps} steps | LLM p50 {llm_p50:.1f}s, step p50 {pct(iv,.5):.1f}s => VM-side V={V:.1f}s/step")
print("action mix:", dict(collections.Counter(kind(s['action']) for g in groups.values() for tr in g.values() for s in tr).most_common(7)))

def evaluate(keyfn, name, K=1, history=False):
    n = hit = anyc = 0; slack_hit = []; spec = 0; hid = 0.0; tot = 0.0
    for g in groups.values():
        for r, tr in g.items():
            for i, s in enumerate(tr):
                if kind(s["action"]) in ("DONE", "FAIL"): continue   # nothing to execute
                n += 1; tot += V
                pre = [keyfn(x) for x in tr[:i]]
                cands = [(o[i]["t"], keyfn(o[i])) for q, o in g.items() if q != r and len(o) > i and o[i]["t"] < s["t"]
                         and (not history or [keyfn(x) for x in o[:i]] == pre)
                         and kind(o[i]["action"]) not in ("DONE", "FAIL")]
                if not cands: continue
                anyc += 1
                cnt = collections.Counter(k for _, k in cands); first = {}
                for t0, k in sorted(cands): first.setdefault(k, t0)
                pick = sorted(cnt, key=lambda k: (-cnt[k], first[k]))[:K]; spec += len(pick)
                if keyfn(s) in pick:
                    # speculation can start only when (a) the sibling's action is known and (b) OUR VM has reached step i's state
                    ready = tr[i - 1]["t"] + V if i else s["t"] - llm_p50
                    win = max(s["t"] - max(first[keyfn(s)], ready), 0)
                    hit += 1; slack_hit.append(win); hid += min(win, V)
    print(f"{name:34s} top-{K}: hit {hit/max(n,1):5.1%}  (have-a-candidate {anyc/max(n,1):5.1%}, precision {hit/max(anyc,1):5.1%})  wasted VM execs/real step {(spec-hit)/max(n,1):.2f}  "
          f"window p50 {pct(slack_hit,.5):.1f}s  VM time hidden {hid/max(tot,1e-9):.1%} of VM-side, {hid/max(tot+n*llm_p50,1e-9):.1%} of step")
print("\n== causal sibling speculation (siblings already issued their step-i action) ==")
for kn in KEYS: evaluate(KEYS[kn], f"sibling-earliest/majority [{kn}]", K=1)
for k in range(2, K + 1): evaluate(elem, "sibling majority [elem]", K=k)
print("\n== + require identical action history (same likely UI state) ==")
evaluate(elem, "sibling same-history [elem]", K=1, history=True)
# ceiling: any sibling (non-causal) ever issues the same key at the same step index
for kn, fn in KEYS.items():
    n = c = 0
    for g in groups.values():
        for r, tr in g.items():
            for i, s in enumerate(tr):
                if kind(s["action"]) in ("DONE", "FAIL"): continue
                n += 1; c += any(len(o) > i and fn(o[i]) == fn(s) for q, o in g.items() if q != r)
    print(f"oracle ceiling, any sibling same step [{kn}]: {c/n:.1%}")
# action-type prediction (cheap): bigram on previous type, leave-one-task-out, vs sibling majority type
big = collections.defaultdict(collections.Counter)
for t, g in groups.items():
    for tr in g.values():
        ks = ["^"] + [kind(s["action"]) for s in tr]
        for a, b in zip(ks, ks[1:]): big[(t, a)][b] += 1
n = ok = 0
for t, g in groups.items():
    for tr in g.values():
        ks = ["^"] + [kind(s["action"]) for s in tr]
        for a, b in zip(ks, ks[1:]):
            c = collections.Counter()
            for (tt, aa), v in big.items():
                if tt != t and aa == a: c += v
            n += 1; ok += bool(c) and c.most_common(1)[0][0] == b
print(f"action-TYPE bigram (leave-one-task-out) top-1: {ok/n:.1%}   (type only, no target)")
