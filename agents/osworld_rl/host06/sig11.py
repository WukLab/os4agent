"""Every failed clone with 'stopped by 11' in all runs on 06, by app; plus how many clones each app made (the denominator)."""
import glob, json, collections
b = json.load(open("grpo_batch32v2.json"))
app = {t: d for d, ts in b.items() for t in ts}
hit, tot, runs = collections.Counter(), collections.Counter(), collections.defaultdict(set)
for p in glob.glob("traces/*/events.jsonl"):
    for l in open(p):
        if '"tfork_clone"' not in l and '"ckpt_clone"' not in l and '"prefix_clone"' not in l:
            continue
        e = json.loads(l)
        a = app.get(e.get("task"), "?")
        tot[a] += 1
        w = " ".join(e["why"]) if isinstance(e.get("why"), list) else str(e.get("why") or "")
        if "stopped by 11" in w or "killed by 11" in w:
            hit[a] += 1
            runs[a].add(p.split("/")[1])
for a in sorted(tot, key=lambda a: -hit[a]):
    print(f"{a:17} clones {tot[a]:6}, SIGSEGV under parasite {hit[a]:3} ({100 * hit[a] / tot[a]:.2f}%)  runs: {sorted(runs[a])[:6]}")
