"""Pick the GRPO task batch (the webarena counterpart of osworld_rl/grpo_batch.json).
  venv/bin/python make_batch.py [--n-retrieve 4 --n-mutate 3 --n-navigate 3 --seed 0] > webarena_batch.json
Shopping-only tasks, outside the 'hard' subset (an 8B policy needs some successes for GRPO reward variance), stratified by task type."""
import argparse, json, random, sys
from pathlib import Path
from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig
from webarena_verified.types.task import WebArenaSite

ap = argparse.ArgumentParser()
ap.add_argument("--n-retrieve", type=int, default=4); ap.add_argument("--n-mutate", type=int, default=3); ap.add_argument("--n-navigate", type=int, default=3)
ap.add_argument("--seed", type=int, default=0); ap.add_argument("--wa", default=str(Path(__file__).resolve().parent.parent / "webarena-verified"))
a = ap.parse_args()
wa = WebArenaVerified(config=WebArenaVerifiedConfig(environments={"__SHOPPING__": {"urls": ["http://localhost:7770"]}}))
hard = set(json.load(open(f"{a.wa}/assets/dataset/subsets/webarena-verified-hard.json"))["task_ids"])
pool = [t for t in wa.get_tasks(sites=[WebArenaSite.SHOPPING]) if t.task_id not in hard]
rng, out = random.Random(a.seed), []
for kind, n in (("retrieve", a.n_retrieve), ("mutate", a.n_mutate), ("navigate", a.n_navigate)):
    c = sorted((t for t in pool if getattr(t, f"is_{kind}_task")), key=lambda t: t.task_id)
    # one task per intent template, so the batch is not 3 instances of the same question
    seen, uniq = set(), []
    for t in rng.sample(c, len(c)):
        if t.intent_template_id not in seen: seen.add(t.intent_template_id); uniq.append(t)
    for t in uniq[:n]:
        out.append(t.task_id); print(f"{kind:8} {t.task_id:4} {t.intent[:100]}", file=sys.stderr)
json.dump({"shopping": out}, sys.stdout, indent=1)
