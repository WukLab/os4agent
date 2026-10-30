"""Progress of the spec tail runs: python3 spec_progress.py [A B]. Steps per rollout as a bar, + speculation stats."""
import glob, json, os, statistics as st, sys, time

for r in sys.argv[1:] or ["A8", "B8", "B8b"]:
    root = r if r.startswith("traces/") else f"traces/spec_tail_{r}"
    if not os.path.exists(f"{root}/events.jsonl"):
        print(f"{r}: not started")
        continue
    ev = [json.loads(l) for l in open(f"{root}/events.jsonl")]
    done = {(e["task"][:8], e["k"]) for e in ev if e["event"] == "rollout_done"}
    end = next((e["t"] for e in ev if e["event"] == "run_done"), None)
    print(f"{r}: {((end or time.time()) - ev[0]['t']) / 60:.1f} min {'(finished)' if end else ''}, rollouts done {len(done)}/{len(glob.glob(root + "/*/*__g*"))}")
    for d in sorted(glob.glob(f"{root}/*/*__g*")):
        n = sum(1 for _ in open(f"{d}/traj.jsonl")) if os.path.exists(f"{d}/traj.jsonl") else 0
        t, k = os.path.basename(d).split("__g")
        skipped = sum('"skipped": "spec"' in l for l in open(f"{d}/traj.jsonl")) if n else 0
        bar = "#" * skipped + "=" * (n - skipped) + "." * (15 - n)
        pass
    sp = [e for e in ev if e["event"] == "spec_exec"]
    if sp:
        hits = [e for e in sp if e["hit"] is not None]
        miss = [e for e in sp if e["hit"] is None]
        med = lambda v: f"{st.median(v):.1f}" if v else "-"
        print(f"   spec: {len(sp)} speculated steps, {len(hits)} hits ({100 * len(hits) / len(sp):.0f}%), fork median {med([e['fork_s'] for e in sp])} s, "
              f"wait on hit {med([e['waited_s'] for e in hits])} s, on miss {med([e['waited_s'] for e in miss])} s, errors {sum(bool(e['error']) for e in sp)}")
        for e in [e for e in sp if e["error"]][:3]:
            print("     error:", e["error"][-160:])
    if w := next((e for e in ev if e["event"] == "spec_warm"), None):
        print(f"   warm: TAGE learned {w['reveals']} steps, book {w['book']} actions")
print("bar: # = step taken from a speculative fork, = = run normally, . = not reached")
