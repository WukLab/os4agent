"""16x8 cap-20 report. Usage: r128_report.py early|final"""
import json, glob, os, sys
from collections import Counter
def ends(r):
    ev = [json.loads(l) for l in open(f"traces/{r}/events.jsonl")]
    t0 = min(e["t"] for e in ev)
    return ev, sorted((e["t"] - t0) / 60 for e in ev if e["event"] == "rollout_done")
ev_rec, rec = ends("rec128_shot")
print(f"live recording: {len(rec)} rollouts, epoch {rec[-1]:.1f} min, errored {sum(1 for e in ev_rec if e['event'] == 'rollout_done' and e.get('error'))}")
ev_p, p = ends("r128_P")
sp = [e for e in ev_p if e["event"] == "spec_exec"]
print(f"replay P: epoch {p[-1]:.1f} min | outcomes {dict(Counter(e.get('outcome') for e in sp))} | spec errors {sum(1 for e in sp if e.get('error'))}")
print(f"  early estimate: P vs live x 0.90 (16x2 replay/live ratio) = {100 * (p[-1] - 0.9 * rec[-1]) / (0.9 * rec[-1]):+.1f}%")
if sys.argv[1] == "final":
    ev_a, a = ends("r128_A")
    print(f"replay A: epoch {a[-1]:.1f} min  ->  P vs A: {100 * (p[-1] - a[-1]) / a[-1]:+.1f}%   (replay/live ratio here {a[-1] / rec[-1]:.2f})")
    for f in (0.5, 0.75, 0.9):
        print(f"  tail after {int(f*100)}% done: A {100 * (a[-1] - a[int(len(a)*f)-1]) / a[-1]:.0f}%  P {100 * (p[-1] - p[int(len(p)*f)-1]) / p[-1]:.0f}%")
    def by_step(r):
        out = {}
        for fn in glob.glob(f"traces/{r}/*/*/traj.jsonl"):
            rid = os.path.basename(os.path.dirname(fn))
            for s in (json.loads(l) for l in open(fn) if l.strip()):
                if "exec_s" in s: out[(rid, s["step_num"])] = (s["exec_s"], s.get("skipped"), s.get("race"))
        return out
    A, P = by_step("r128_A"), by_step("r128_P")
    hs = [(A[k][0], P[k][0]) for k in P if (P[k][1] == "spec" or P[k][2]) and k in A]
    ot = [(A[k][0], P[k][0]) for k in P if not (P[k][1] == "spec" or P[k][2]) and k in A]
    print(f"  env time on speculated steps {sum(x for x, _ in hs)/60:.1f} -> {sum(y for _, y in hs)/60:.1f} min ({len(hs)} steps); other steps {sum(x for x, _ in ot)/60:.1f} -> {sum(y for _, y in ot)/60:.1f} min")
    print("  last 8 finish A:", [round(x, 1) for x in a[-8:]], "\n  last 8 finish P:", [round(x, 1) for x in p[-8:]])
