"""Model-free speculation predictors on a GRPO minibatch, no LLM.   python analyze_markov.py traces/<run>
Predicts the next ABSTRACT action ('click@role|name', or the exact code for non-clicks) and scores it against what the model really did.
 markov1/markov2 : next-action n-gram, trained on OTHER tasks (leave-one-task-out), back-off 2->1   (SpecBox / toolspec style)
 +feasible       : drop click candidates whose element is not visible in OUR current a11y tree      (PASTE symbolic argument mapping)
 propensity      : Bayes  P(click e | e visible, click step), ranks visible elements                 (LOTO)
 sibling         : causal GRPO-sibling prediction (a sibling already issued its step-i action)
Non-sibling predictors can start as soon as our VM has reached step i (window <= LLM latency); sibling ones also wait for the sibling."""
import collections, glob, gzip, json, os, re, sys, xml.etree.ElementTree as ET
R = sys.argv[1]; sys.argv = ["x", R, "1"]
exec(open("analyze_gui.py").read().split('print("\\n== causal')[0])   # groups, kind(), V, llm_p50, pct, ts, ...
from a11y_hit import _box, INTERACTIVE
dirs = {}
for d in glob.glob(f"{R}/results/*/*/*/*/*__g*"):
    m = re.match(r"(.*)__g(\d+)$", os.path.basename(d)); dirs[(m.group(1), int(m.group(2)))] = d
CLICKS = ("click", "doubleClick", "rightClick", "tripleClick")
def A(s):  # abstract action key
    k = kind(s["action"])
    if k in CLICKS:
        h = s.get("a11y_hit"); return f"click@{h['role']}|{h['name']}" if h and h.get("key") else "click@?"
    return exact(s)
def visible(task, g, s):
    f = f"{dirs[(task, g)]}/step_{s['step_num']}_{s['action_timestamp']}.a11y.xml.gz"
    if not os.path.exists(f): return None
    try: root = ET.fromstring(gzip.open(f, "rt").read())
    except Exception: return None
    return {f"{e.tag}|{e.get('name', '')}" for e in root.iter() if e.tag in INTERACTIVE and _box(e)}
rows = []  # per step: task, g, i, s, abstract key, prev1, prev2, visible set
for t, g in groups.items():
    for r, tr in g.items():
        for i, s in enumerate(tr):
            if kind(s["action"]) in ("DONE", "FAIL"): continue
            rows.append(dict(t=t, r=r, i=i, s=s, a=A(s), p1=A(tr[i - 1]) if i else "^", p2=A(tr[i - 2]) if i > 1 else "^", vis=visible(t, r, s)))
print(f"{len(rows)} executable steps; abstract click mapped for {sum(x['a'] != 'click@?' for x in rows if x['a'].startswith('click@'))}/{sum(x['a'].startswith('click@') for x in rows)} clicks; tree available for {sum(x['vis'] is not None for x in rows)} steps")
# training tables per task
mk1, mk2 = collections.defaultdict(lambda: collections.defaultdict(collections.Counter)), collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
clicked, present = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter)
for x in rows:
    mk1[x["t"]][x["p1"]][x["a"]] += 1; mk2[x["t"]][(x["p2"], x["p1"])][x["a"]] += 1
    if x["a"].startswith("click@") and x["vis"]:
        for e in x["vis"]: present[x["t"]][e] += 1
        if x["a"] != "click@?": clicked[x["t"]][x["a"][6:]] += 1
def loto(tab, own, key):
    c = collections.Counter()
    for t, d in tab.items():
        if t != own: c.update(d.get(key, {}))
    return c
def loto_flat(tab, own):
    c = collections.Counter()
    for t, d in tab.items():
        if t != own: c.update(d)
    return c
def markov(x, K, feasible):
    c = loto(mk2, x["t"], (x["p2"], x["p1"])) or loto(mk1, x["t"], x["p1"])
    out = []
    for a, _ in c.most_common():
        if a == "click@?": continue
        if feasible and x["vis"] is not None and a.startswith("click@") and a[6:] not in x["vis"]: continue
        out.append(a)
        if len(out) == K: break
    return out
def propensity(x, K):
    if not x["vis"]: return []
    ck, pr = loto_flat(clicked, x["t"]), loto_flat(present, x["t"])
    sc = sorted(x["vis"], key=lambda e: -(ck[e] + .05) / (pr[e] + 2))
    return [f"click@{e}" for e in sc[:K]]
def combo(x, K):  # Markov feasible; fill remaining slots from propensity
    m = markov(x, K, True); return m + [p for p in propensity(x, K) if p not in m][:K - len(m)]
byk = {(x["t"], x["r"], x["i"]): x for x in rows}
def sibling(x, K):
    g = groups[x["t"]]; cands = [(o[x["i"]]["t"], A(o[x["i"]])) for q, o in g.items() if q != x["r"] and len(o) > x["i"] and o[x["i"]]["t"] < x["s"]["t"] and kind(o[x["i"]]["action"]) not in ("DONE", "FAIL")]
    cnt = collections.Counter(a for _, a in cands); first = {}
    for t0, a in sorted(cands): first.setdefault(a, t0)
    return sorted(cnt, key=lambda a: (-cnt[a], first[a]))[:K], first
def run(name, pred, K, uses_sib=False):
    n = hit = spec = 0; hid = 0.0; hitc = nclick = 0
    for x in rows:
        n += 1; s, tr = x["s"], groups[x["t"]][x["r"]]; isc = x["a"].startswith("click@"); nclick += isc
        p = pred(x, K); first = {}
        if uses_sib: p, first = p
        spec += len(p)
        if x["a"] in p and x["a"] != "click@?":
            hit += 1; hitc += isc
            ready = tr[x["i"] - 1]["t"] + V if x["i"] else s["t"] - llm_p50
            start = max(ready, first.get(x["a"], 0)); hid += min(max(s["t"] - start, 0), V)
    print(f"{name:30s} K={K}: hit {hit/n:5.1%}  (clicks {hitc/max(nclick,1):5.1%})  wasted execs/step {(spec-hit)/n:4.2f}  VM time hidden {hid/(n*V):5.1%}  step time hidden {hid/(n*(V+llm_p50)):4.1%}")
for K in map(int, os.environ.get("KS", "1,3").split(",")):
    run("markov1+2 (LOTO)", lambda x, K: markov(x, K, False), K)
    run("markov + feasible (PASTE-like)", lambda x, K: markov(x, K, True), K)
    run("propensity (Bayes, visible)", propensity, K)
    run("markov+feasible, fill=propensity", combo, K)
    run("sibling (causal, abstract)", sibling, K, True)
    run("sibling else markov+propensity", lambda x, K: (lambda sp: (sp[0] + [p for p in combo(x, K) if p not in sp[0]][:K - len(sp[0])], sp[1]))(sibling(x, K)), K, True)
