"""python summarize.py traces/<run>   -> GRPO minibatch report (rewards per group, LLM latency/tail, batch size, a11y sibling agreement)."""
import collections, glob, json, os, re, statistics as st, sys
R = sys.argv[1]; pct = lambda xs, q: sorted(xs)[min(len(xs) - 1, int(len(xs) * q))] if xs else float("nan")
groups, steps_of = collections.defaultdict(dict), {}
for d in glob.glob(f"{R}/results/*/*/*/*/*__g*"):
    m = re.match(r"(.*)__g(\d+)$", os.path.basename(d)); task, g = m.group(1), int(m.group(2))
    rf = f"{d}/result.txt"; reward = float(open(rf).read()) if os.path.exists(rf) else None
    traj = [json.loads(l) for l in open(f"{d}/traj.jsonl")] if os.path.exists(f"{d}/traj.jsonl") else []
    traj = [t for t in traj if "step_num" in t]
    groups[task][g] = reward; steps_of[(task, g)] = traj
done = {k: v for k, v in groups.items() if any(x is not None for x in v.values())}
print(f"rollouts started {sum(len(v) for v in groups.values())}, finished {sum(x is not None for v in groups.values() for x in v.values())}")
mixed = 0
for t, v in sorted(done.items()):
    rs = [x for x in v.values() if x is not None]; sd = st.pstdev(rs) if len(rs) > 1 else 0; mixed += sd > 0
    print(f"  {t[:8]}  n={len(rs)} mean={st.mean(rs):.2f} std={sd:.2f}  rewards={sorted(rs)}")
print(f"groups with reward variance (usable GRPO signal): {mixed}/{len(done)}")
allr = [x for v in done.values() for x in v.values() if x is not None]
if allr: print(f"overall mean reward {st.mean(allr):.3f}")
ns = [len(t) for t in steps_of.values() if t]
if ns: print(f"steps/rollout: mean {st.mean(ns):.1f} p50 {pct(ns,.5)} max {max(ns)}")
# LLM
L = [json.loads(l) for l in open(f"{R}/llm.jsonl")] if os.path.exists(f"{R}/llm.jsonl") else []
lat = [r["t_end"] - r["t_start"] for r in L]
if lat: print(f"LLM requests {len(lat)}  latency p50 {pct(lat,.5):.2f}s p90 {pct(lat,.9):.2f}s p99 {pct(lat,.99):.2f}s max {max(lat):.2f}s  (tail/p50 = {max(lat)/pct(lat,.5):.1f}x)")
M = [json.loads(l) for l in open(f"{R}/vllm_metrics.jsonl")] if os.path.exists(f"{R}/vllm_metrics.jsonl") else []
run = [m["running"] for m in M if m.get("running") is not None]
if run:
    busy = [x for x in run if x > 0]
    print(f"vLLM batch size (1 Hz, {len(run)} samples): mean {st.mean(run):.2f}, when busy mean {st.mean(busy) if busy else 0:.2f}, p90 {pct(run,.9)}, max {max(run)}; GPU busy {len(busy)/len(run):.0%} of time; max waiting {max(m.get('waiting') or 0 for m in M)}; max KV {max(m.get('kv') or 0 for m in M):.1%}")
# a11y / sibling agreement (NON-causal: compares each rollout to the modal element among its siblings at the same step index)
n = keyed = agree = comparable = 0
for t in done:
    sib = {g: steps_of[(t, g)] for g in done[t]}
    for g, tr in sib.items():
        for i, s in enumerate(tr):
            h = s.get("a11y_hit")
            if h is None: continue
            n += 1; keyed += h.get("key") is not None
            if h.get("key") is None: continue
            others = [x[i]["a11y_hit"]["key"] for gg, x in sib.items() if gg != g and len(x) > i and x[i].get("a11y_hit") and x[i]["a11y_hit"].get("key")]
            if others:
                comparable += 1; agree += collections.Counter(others).most_common(1)[0][0] == h["key"]
print(f"clicks {n}, mapped to a11y element {keyed} ({keyed/max(n,1):.0%}); sibling element agreement at same step {agree}/{comparable} ({agree/max(comparable,1):.0%}, non-causal upper bound)")
# --- VM-side bottleneck view ---
import datetime
H = [json.loads(l) for l in open(f"{R}/host.jsonl")] if os.path.exists(f"{R}/host.jsonl") else []
if H:
    busy = [h["user"] + h["sys"] for h in H]
    print(f"host CPU busy mean {st.mean(busy):.0%} p95 {pct(busy,.95):.0%} (iowait p95 {pct([h['iowait'] for h in H],.95):.1%}); load1 max {max(h['load1'] for h in H):.1f}; min free mem {min(h['mem_avail_gb'] for h in H):.1f} GB; disk write p95 {pct([h['disk_w_MBps'] for h in H],.95):.0f} MB/s")
ts = lambda s: datetime.datetime.strptime(s, "%Y%m%d@%H%M%S%f").timestamp()
iv, active, tail = [], [], []
for (t, g), tr in steps_of.items():
    if len(tr) < 2: continue
    T = [ts(s["action_timestamp"]) for s in tr]; iv += [b - a for a, b in zip(T, T[1:])]; active.append(T[-1] - T[0])
    rf = glob.glob(f"{R}/results/*/*/*/*/{t}__g{g}/result.txt")
    if rf: tail.append(os.path.getmtime(rf[0]) - T[-1])
if iv:
    llm_p50 = pct(lat, .5) if lat else 0
    print(f"step interval p50 {pct(iv,.5):.1f}s p90 {pct(iv,.9):.1f}s  => minus LLM p50 {llm_p50:.1f}s = VM+harness {pct(iv,.5)-llm_p50:.1f}s/step ({(pct(iv,.5)-llm_p50)/pct(iv,.5):.0%} of a step; includes the fixed 3s post-action sleep)")
    print(f"per rollout: active {st.mean(active):.0f}s, then settle+eval {st.mean(tail) if tail else float('nan'):.0f}s after the last step (fixed 20s settle + evaluator)")
