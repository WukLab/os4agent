"""Replay A/B: epoch, tail (by live rollouts), per-run speculation stats, peak memory."""
import json, sys, os, statistics as st
def load(r):
    ev = [json.loads(l) for l in open(f"traces/{r}/events.jsonl")]
    t0 = min(e["t"] for e in ev if e["event"] in ("boot", "tfork_clone", "rollout_done"))
    first = min(e["t"] for e in ev if e["event"] == "tfork_clone") if any(e["event"] == "tfork_clone" for e in ev) else t0
    done = sorted(e["t"] - first for e in ev if e["event"] == "rollout_done")
    return ev, done
res = {}
for r in sys.argv[1:]:
    ev, d = load(r); n = len(d); end = d[-1]; res[r] = end
    tail = lambda live: 100 * (end - d[n - live - 1]) / end if n > live else 0
    errs = sum(1 for e in ev if e["event"] == "rollout_done" and e.get("error"))
    sp = [e for e in ev if e["event"] == "spec_exec"]
    hits = [e for e in sp if e.get("hit") is not None]
    mem = os.path.exists(f"traces/{r}/mem.jsonl") and max((json.loads(l).get("used_gib") or json.loads(l).get("total_gib") or 0) for l in open(f"traces/{r}/mem.jsonl")) or None
    print(f"{r}: {n} rollouts ({errs} errored), epoch {end/60:.2f} min | tail <16 live {tail(16):.0f}%  <8 live {tail(8):.0f}%  <4 live {tail(4):.0f}% | peak mem {mem}")
    if sp:
        print(f"   speculated {len(sp)} steps, hits {len(hits)} ({100*len(hits)/len(sp):.0f}%), errors {sum(1 for e in sp if e.get('error'))}, "
              f"saved/hit median {st.median([e.get('saved_s', 0) for e in hits]) if hits and 'saved_s' in hits[0] else 'n/a'}")
a, b = sys.argv[1], sys.argv[2]
print(f"epoch change B vs A: {100*(res[b]-res[a])/res[a]:+.1f}%")
