"""What would an a11y-ONLY observation look like?  python analyze_a11y_obs.py traces/<run>
Linearize each saved pre-action tree to rows 'idx | role | name | x,y,w,h' (showing, named elements) and measure size, target coverage, ambiguity,
and whether an ORDINAL element id would be stable across siblings at the same node."""
import collections, glob, gzip, os, re, sys, xml.etree.ElementTree as ET
R = sys.argv[1]; sys.argv = ["x", R, "1"]
exec(open("analyze_gui.py").read().split('print("\\n== causal')[0])
sys.path.insert(0, "."); from a11y_hit import _box, INTERACTIVE
dirs = {}
for d in glob.glob(f"{R}/results/*/*/*/*/*__g*"):
    m = re.match(r"(.*)__g(\d+)$", os.path.basename(d)); dirs[(m.group(1), int(m.group(2)))] = d
def rows_of(t, g, s):
    f = f"{dirs[(t, g)]}/step_{s['step_num']}_{s['action_timestamp']}.a11y.xml.gz"
    if not os.path.exists(f): return None
    try: root = ET.fromstring(gzip.open(f, "rt").read())
    except Exception: return None
    out = []
    for e in root.iter():
        b = _box(e); nm = (e.get("name") or "").strip()
        if b and nm: out.append((e.tag, nm, b))
    return out
sizes, chars, cov, uniq, tot = [], [], 0, 0, 0
ordinal = {}
for t, g in groups.items():
    for r, tr in g.items():
        for i, s in enumerate(tr):
            if kind(s["action"]) not in ("click", "doubleClick", "rightClick"): continue
            rows = rows_of(t, r, s)
            if not rows: continue
            h = s.get("a11y_hit"); tot += 1
            sizes.append(len(rows)); chars.append(sum(len(f"{k}|{role}|{nm}|{b[0]},{b[1]},{b[2]},{b[3]}") + 4 for k, (role, nm, b) in enumerate(rows)))
            if not h or not h.get("key"): continue
            tgt = [k for k, (role, nm, b) in enumerate(rows) if role == h["role"] and nm == h["name"] and list(b) == h["bbox"]]
            if tgt:
                cov += 1; uniq += sum(1 for role, nm, _ in rows if (role, nm) == (h["role"], h["name"])) == 1
                ordinal[(t, r, i)] = (tuple(elem(x) for x in tr[:i]), elem(s), tgt[0], len(rows))
print(f"click steps with a saved tree: {tot}")
print(f"rows per observation (named, showing): p50 {pct(sizes,.5)} p90 {pct(sizes,.9)}; chars p50 {pct(chars,.5):,} p90 {pct(chars,.9):,}  => ~{pct(chars,.5)/3.5:,.0f} tokens p50, ~{pct(chars,.9)/3.5:,.0f} p90  (pixel prompt today: ~14,100)")
print(f"target element present in the linearized list: {cov}/{tot} = {cov/tot:.0%}; target (role,name) unique in the list: {uniq}/{cov} = {uniq/max(cov,1):.0%}")
by = collections.defaultdict(list)
for k, (hist, key, idx, n) in ordinal.items(): by[(k[0], hist, key)].append(idx)
pairs = same = 0
for v in by.values():
    for a in range(len(v)):
        for b in range(a + 1, len(v)): pairs += 1; same += v[a] == v[b]
print(f"sibling pairs at the same node picking the same element: {pairs}; ORDINAL id identical in {same/max(pairs,1):.0%} of them (stable id = 100% by construction)")
