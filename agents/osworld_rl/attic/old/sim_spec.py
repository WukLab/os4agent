"""Group-tree speculation simulator.   python sim_spec.py traces/<run>
Node = (task, action history). A rollout at node N needs its next action. Branches (N, action) are CoW-forked VM states:
  * sibling branch : a sibling at N really executed its action at time t_s            (free, shared)
  * predicted branch: launched at T_N (first time any rollout reached N) for top-B predicted actions, cost V VM-seconds each
A rollout whose real action matches an existing branch ADOPTS it (fork-in cost c_f) instead of executing:
  saved = clip(t_real - launch, 0, V) - c_f.   Unadopted predicted branches are waste (discarded clones)."""
import collections, os, sys
R = sys.argv[1]
src = open("analyze_markov.py").read(); exec(src.split("byk = ")[0])   # rows, markov(), propensity(), combo(), groups, V, llm_p50 ...
AK = lambda s: A(s) if A(s) != "click@?" else coarse(s)
mem = collections.defaultdict(list)  # node -> [row]
for x in rows:
    tr = groups[x["t"]][x["r"]]; node = (x["t"], tuple(AK(y) for y in tr[:x["i"]])); x["node"] = node
    x["ready"] = tr[x["i"] - 1]["t"] + V if x["i"] else x["s"]["t"] - llm_p50; mem[node].append(x)
def simulate(Bfn, cc, cf, label):
    n = len(rows); saved = 0.0; npred = nadopt_pred = nadopt_sib = 0; wasted = 0
    for node, ms in mem.items():
        lead = min(ms, key=lambda x: x["ready"]); TN = lead["ready"]; B = Bfn(lead["i"])
        pred = combo(lead, B)[:B] if B else []
        pred = [p for p in pred if p != "click@?"]; npred += len(pred); used = set()
        sib = [(AK(m["s"]), m["s"]["t"], id(m)) for m in ms]
        for m in ms:
            best, kind_ = 0.0, None
            for k, L, owner in sib:
                if owner != id(m) and k == AK(m["s"]):
                    sv = min(max(m["s"]["t"] - L, 0), V) - cf
                    if sv > best: best, kind_ = sv, "sib"
            if m["a"] in pred:
                sv = min(max(m["s"]["t"] - (TN + cc), 0), V) - cf
                if sv > best: best, kind_ = sv, "pred"; used.add(m["a"])
            if best > 0:
                saved += best; nadopt_sib += kind_ == "sib"; nadopt_pred += kind_ == "pred"
        wasted += len(set(pred) - used)
    print(f"{label:34s} saved {saved/(n*(V+llm_p50)):5.1%} of step time | adopt sib {nadopt_sib/n:5.1%} pred {nadopt_pred/n:5.1%} of steps | spec branches/step {npred/n:4.2f}, wasted {wasted/n:4.2f} (= {wasted*V/(n*V):4.0%} extra VM-seconds)")
gate = lambda i: 8 if i == 0 else 5 if i <= 2 else 3 if i <= 5 else 0
print(f"V={V:.1f}s LLM p50={llm_p50:.1f}s; cc = clone-out cost for a speculative branch, cf = fork-in cost on adoption\n")
simulate(lambda i: 0, .5, .5, "adopt-only (no prediction)")
for B in (3, 5, 8): simulate(lambda i, B=B: B, .5, .5, f"adopt + predicted B={B} (all steps)")
simulate(gate, .5, .5, "adopt + gated B(i)=8/5/3/0")
print("\nclone-cost sensitivity, gated:")
for c in (.2, 1, 3, 6): simulate(gate, c, c, f"  cc=cf={c}s")

# ---- confidence-gated candidates: speculate only if P(hit) >= theta  (EV rule: P * saved_time > cost) ----
def scored(x):
    out = {}
    c = loto(mk2, x["t"], (x["p2"], x["p1"])) or loto(mk1, x["t"], x["p1"]); tot = sum(c.values()) or 1
    for a, v in c.items():
        if a != "click@?" and not (x["vis"] is not None and a.startswith("click@") and a[6:] not in x["vis"]): out[a] = v / tot
    if x["vis"]:
        ck, pr = loto_flat(clicked, x["t"]), loto_flat(present, x["t"])
        for e in x["vis"]: out[f"click@{e}"] = max(out.get(f"click@{e}", 0), (ck[e] + .05) / (pr[e] + 2))
    return out
_cache = {}
def conf_combo(theta, Bmax=8):
    def f(x, B):
        k = id(x)
        if k not in _cache: _cache[k] = sorted(scored(x).items(), key=lambda kv: -kv[1])
        return [a for a, p in _cache[k] if p >= theta][:Bmax]
    return f
print("\nconfidence-gated (cc=cf=0.5s):")
_orig = combo
for th in (.5, .3, .2, .1, .05, .02):
    combo = conf_combo(th); simulate(lambda i: 8, .5, .5, f"  theta={th}")
