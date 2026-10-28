"""Grow the OSWorld GRPO batch: keep grpo_batch.json's tasks and add more per app from test_nogdrive.json (seeded).
  python make_osw_batch.py [--add chrome=2,gimp=2,...] [--seed 0] > grpo_batch32.json
Skips tasks that need the proxy and 'infeasible' tasks (no reward variance to learn from); single-app domains only."""
import argparse, json, random, sys
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="grpo_batch.json"); ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--add", default="chrome=2,gimp=2,libreoffice_calc=4,libreoffice_impress=4,libreoffice_writer=3,os=2,thunderbird=2,vlc=1,vs_code=2")
ap.add_argument("--examples", default="OSWorld/evaluation_examples")
a = ap.parse_args()
ex = Path(a.examples); base = json.load(open(a.base)); pool = json.load(open(ex / "test_nogdrive.json")); rng = random.Random(a.seed)
out = {d: list(v) for d, v in base.items()}
for item in a.add.split(","):
    dom, n = item.split("="); have = set(out.get(dom, []))
    ok = [i for i in sorted(pool[dom]) if i not in have
          and not (t := json.load(open(ex / "examples" / dom / f"{i}.json"))).get("proxy") and t["evaluator"].get("func") != "infeasible"]
    pick = rng.sample(ok, int(n)); out.setdefault(dom, []).extend(pick)
    for i in pick: print(f"+ {dom:20} {i[:8]} {json.load(open(ex / 'examples' / dom / f'{i}.json'))['instruction'][:90]}", file=sys.stderr)
print(f"{sum(len(v) for v in out.values())} tasks", file=sys.stderr)
json.dump(out, sys.stdout, indent=1)
