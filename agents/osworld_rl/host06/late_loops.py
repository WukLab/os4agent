"""Rollouts still running after step 10: are they looping? Per step window, share of steps repeating the previous
action; in steps 11-15, how many distinct actions (1 = one action over and over, 2 = alternating); do they succeed late."""
import glob, json, os, statistics as st, sys
sys.path.insert(0, ".")
from toolspec.online import web_step
for r in sys.argv[1:]:
    rows = []
    for f in glob.glob(f"traces/{r}/*/*/traj.jsonl"):
        d = f.rsplit("/", 1)[0]
        keys = [web_step(d, s)[1] for s in (json.loads(l) for l in open(f) if l.strip()) if "action_timestamp" in s]
        rew = float(open(f"{d}/result.txt").read() or 0) if os.path.exists(f"{d}/result.txt") else 0.0
        rows.append((keys, rew))
    late = [(k, rw) for k, rw in rows if len(k) > 10]
    rep = lambda k, lo, hi: [a == b and a is not None for a, b in zip(k[lo - 1:hi - 1], k[lo:hi])]
    print(f"== {r}: {len(rows)} rollouts, {len(late)} still running after step 10 ({100 * len(late) / len(rows):.0f}%)")
    for lo, hi in ((2, 5), (6, 10), (11, 15)):
        v = [x for k, _ in late for x in rep(k, lo, hi)]
        print(f"   steps {lo:2}-{hi:2}: {100 * sum(v) / max(len(v), 1):3.0f}% repeat the previous action")
    distinct = [len(set(k[10:15])) for k, _ in late if len(k) >= 15]
    print(f"   distinct actions in steps 11-15 (rollouts reaching 15): 1 -> {sum(x == 1 for x in distinct)}, 2 -> {sum(x == 2 for x in distinct)}, "
          f"3+ -> {sum(x >= 3 for x in distinct)} of {len(distinct)}")
    print(f"   success among them: {sum(rw > 0 for _, rw in late)} of {len(late)} (all rollouts: {sum(rw > 0 for _, rw in rows)} of {len(rows)})")
