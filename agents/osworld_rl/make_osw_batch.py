"""Grow an OSWorld GRPO batch: keep --base's tasks and add a seeded sample per app from test_nogdrive.json.

  python make_osw_batch.py > grpo_batch64.json

Skips proxy-only and infeasible tasks (no reward variance to learn from).
"""
import argparse, json, random, sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="grpo_batch32v2.json")
ap.add_argument("--add", default="chrome=8,gimp=4,libreoffice_calc=8,libreoffice_impress=6,libreoffice_writer=4,vlc=2",
                help="tasks to add per app (thunderbird / vs_code / os are excluded from the comparison)")
ap.add_argument("--examples", default="OSWorld/evaluation_examples")
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()

ex = Path(a.examples)
pool = json.load(open(ex / "test_nogdrive.json"))
out = {d: list(v) for d, v in json.load(open(a.base)).items()}
rng = random.Random(a.seed)
for item in a.add.split(","):
    dom, n = item.split("=")
    tasks = {i: json.load(open(ex / "examples" / dom / f"{i}.json")) for i in sorted(pool[dom]) if i not in out.get(dom, [])}
    ok = [i for i, t in tasks.items() if not t.get("proxy") and t["evaluator"].get("func") != "infeasible"]
    pick = rng.sample(ok, int(n))
    out.setdefault(dom, []).extend(pick)
    for i in pick:
        print(f"+ {dom:20} {i[:8]} {tasks[i]['instruction'][:90]}", file=sys.stderr)
print(f"{sum(len(v) for v in out.values())} tasks", file=sys.stderr)
json.dump(out, sys.stdout, indent=1)
