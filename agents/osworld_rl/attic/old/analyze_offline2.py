"""(1) allocation filter via split-half   (2) no-thought latency estimate from logged tokens.   python analyze_offline2.py traces/<run>"""
import glob, itertools, json, os, re, sys, statistics as st
import numpy as np
R = sys.argv[1]
rew = {}
for d in glob.glob(f"{R}/results/*/*/*/*/*__g*"):
    m = re.match(r"(.*)__g(\d+)$", os.path.basename(d))
    if os.path.exists(f"{d}/result.txt"): rew.setdefault(m.group(1), {})[int(m.group(2))] = float(open(f"{d}/result.txt").read())
G = {t: v for t, v in rew.items() if len(v) == 8}
mixed = lambda xs: len(set(xs)) > 1
print(f"== (1) allocation filter, {len(G)} groups of 8; 'history' = 4 rollouts, 'next' = the other 4 (all {len(list(itertools.combinations(range(8),4)))} splits averaged)")
def run(rule, eps=0.0):
    kept = sig_kept = sig_all = sig_lost = 0.0; n = 0
    for t, v in G.items():
        gs = sorted(v)
        for S in itertools.combinations(gs, 4):
            nxt = [g for g in gs if g not in S]; hist = [v[g] for g in S]; fut = mixed([v[g] for g in nxt])
            keep = rule(hist); p = 1.0 if keep else eps
            kept += p; sig_kept += p * fut; sig_all += fut; n += 1
    return kept / n, sig_kept / n, sig_all / n
base = run(lambda h: True)
print(f"   no filter       : run 100% of groups, {base[2]:.0%} of groups are mixed in 'next' (signal per rollout run = {base[2]:.0%})")
for nm, rule, eps in (("keep if history mixed", mixed, 0.0), ("... + 25% explore of uniform-history groups", mixed, 0.25), ("... + 50% explore", mixed, 0.5)):
    k, s, a = run(rule, eps)
    print(f"   {nm:44s}: run {k:4.0%} of groups; signal captured {s/a:4.0%} of all signal groups; signal per rollout run {s/k:4.0%} (x{(s/k)/(a):.2f} vs no filter)")
print("\n== (2) no-thought estimate from logged responses")
L = [json.loads(l) for l in open(f"{R}/llm.jsonl")]
X, y, think = [], [], []
for r in L:
    try: j = json.loads(r["resp"]); u = j["usage"]; txt = j["choices"][0]["message"]["content"] or ""
    except Exception: continue
    ct, pt = u["completion_tokens"], u["prompt_tokens"]; lat = r["t_end"] - r["t_start"]; run = (r["metrics_at_start"].get("running") or 0)
    th = txt.split("Action:")[0]; frac = len(th) / max(len(txt), 1)
    X.append([1, ct, pt / 1000, run]); y.append(lat); think.append(ct * frac)
X, y = np.array(X, float), np.array(y)
beta, *_ = np.linalg.lstsq(X, y, rcond=None)
res = y - X @ beta; r2 = 1 - (res ** 2).sum() / ((y - y.mean()) ** 2).sum()
print(f"   {len(y)} requests; completion tokens p50 {np.median(X[:,1]):.0f}, thought tokens p50 {np.median(think):.0f} ({np.median(think)/max(np.median(X[:,1]),1):.0%} of output), prompt tokens p50 {np.median(X[:,2])*1000:.0f}")
print(f"   latency ~ {beta[0]:.2f}s + {beta[1]*1000:.0f} ms/output-token + {beta[2]:.2f}s/1k prompt tokens + {beta[3]:.2f}s/concurrent req   (R2={r2:.2f})")
dec = beta[1] * np.array(think); new = y - dec
print(f"   LLM latency p50 {np.median(y):.2f}s -> ~{np.median(new):.2f}s without thought tokens (p90 {np.percentile(y,90):.1f}s -> {np.percentile(new,90):.1f}s)")
V = 9.1; print(f"   step time p50 13.8s -> ~{13.8-(np.median(y)-np.median(new)):.1f}s  ({(np.median(y)-np.median(new))/13.8:.0%} of the step); accuracy impact NOT measurable offline")
