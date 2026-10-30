"""Checks of one osw_run.py run with the tree-closed lazy cache (--prefix-tree, --prefix-lazy-start):
  tree      every cached entry's parent is cached (index.json now; and after every save / eviction, replayed from the
            run's events in order)
  forks     per rollout: group-start copies + materializations; shared clones (prefix_hit_clone copies=k)
  cache     saves by depth, hits by depth, skipped saves by reason, evictions by depth and reason

  python3 -I tree_check.py <run dir> <cache dir>
"""
import collections, json, sys

run, cache = sys.argv[1], sys.argv[2]
ev = [json.loads(l) for l in open(f"{run}/events.jsonl") if l.strip()]
idx = json.load(open(f"{cache}/index.json"))
c = collections.Counter(e["event"] for e in ev)

bad = [k for k, e in idx.items() if e and e.get("parent") and e["parent"] not in idx]
print(f"  tree now: {len(idx)} entries, depths {dict(sorted(collections.Counter(e.get('depth') for e in idx.values() if e).items()))}, "
      f"entries whose parent is not cached: {len(bad)}")
# over the run: the cache at its start (index minus this run's saves, plus its evictions), then each save / eviction
saved = {e["key"]: e.get("parent") for e in ev if e["event"] == "prefix_saved"}
parent = {k: (e or {}).get("parent") for k, e in idx.items()} | saved
live = (set(idx) - set(saved)) | {e["key"] for e in ev if e["event"] == "prefix_evict" and e.get("key") and e["key"] not in saved}
orphan_saves = holes = 0
for e in ev:
    if e["event"] == "prefix_saved":
        orphan_saves += bool(e.get("parent")) and e["parent"] not in live
        live.add(e["key"])
    elif e["event"] == "prefix_evict" and e.get("key"):
        holes += any(parent.get(k) == e["key"] for k in live if k != e["key"])
        live.discard(e["key"])
print(f"  over the run: saves under an uncached parent {orphan_saves}, evictions of an entry with a cached child {holes}")

forks = [e for e in ev if e["event"] == "fork"]
mats = [e for e in ev if e["event"] == "prefix_materialize"]
clones = [e for e in ev if e["event"] == "prefix_hit_clone" and e.get("ok")]
rolls = c["rollout_done"]
print(f"  forks: group-start copies {sum(e.get('copies', 0) for e in forks)} ({sum(bool(e.get('lazy_start')) for e in forks)} of "
      f"{len(forks)} groups lazy-start), materializations {len(mats)} for {rolls} rollouts "
      f"(by depth {dict(sorted(collections.Counter(e['depth'] for e in mats).items()))}, mean {sum(e['secs'] for e in mats) / max(len(mats), 1):.1f} s); "
      f"clones for them {len(clones)} (copies {dict(sorted(collections.Counter(e.get('copies', 1) for e in clones).items()))})")
hits = [e for e in ev if e["event"] == "prefix_hit"]
saves = [e for e in ev if e["event"] == "prefix_saved"]
print(f"  hits {len(hits)} by step {dict(sorted(collections.Counter(e['step'] for e in hits).items()))}; "
      f"saves {len(saves)} by step {dict(sorted(collections.Counter(e['step'] for e in saves).items()))}")
print(f"  save skipped {dict(collections.Counter(e.get('reason') for e in ev if e['event'] == 'prefix_save_skipped'))}; "
      f"evictions {c['prefix_evict']} by depth {dict(sorted(collections.Counter(e.get('depth') for e in ev if e['event'] == 'prefix_evict').items(), key=str))} "
      f"reason {dict(collections.Counter(e.get('reason') for e in ev if e['event'] == 'prefix_evict'))}")
print(f"  failures: save {c['prefix_save_failed']}, clone attempts {sum(1 for e in ev if e['event'].endswith('clone') and not e.get('ok'))}, "
      f"group errors {c['group_error']}, rollout errors {sum(1 for e in ev if e['event'] == 'rollout_done' and e.get('error'))}")
