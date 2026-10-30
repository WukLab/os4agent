"""Summaries of osw_run.py result directories.

  python3 analyze.py progress <run>...                       groups / rollouts / errors / clone retries per run
  python3 analyze.py memory tfork=<run> criu=<run> aenv=<run>[,<extra run>]   per-group memory table + run peaks
  python3 analyze.py clones <run>                            fork attempts, failures and their CRIU errors
"""
import collections, glob, json, re, statistics as st, sys
from pathlib import Path


def events(run):
    return [json.loads(l) for l in open(Path(run) / "events.jsonl")]


def rollouts(run):
    for t in glob.glob(f"{run}/*/*__g*/timing.json"):
        yield Path(t).parent.name.split("__g")[0], json.load(open(t))


def clone_attempts(evs):
    return [e for e in evs if e["event"] in ("tfork_clone", "ckpt_clone") and "ok" in e]


def progress(runs):
    for run in runs:
        evs = events(run)
        c = collections.Counter(e["event"] for e in evs)
        bad = [e for e in clone_attempts(evs) if not e["ok"]]
        errs = [tm for _, tm in rollouts(run) if tm.get("error")]
        print(f"{run}: forks {c['fork']}  groups done {c['group_done']}  group errors {c['group_error']}  "
              f"rollouts {c['rollout_done']} (errors {len(errs)})  failed clone attempts {len(bad)}")
        for e in evs:
            if e["event"] == "group_error":
                print(f"   group_error {e['task'][:8]}: {e['error'][:160]}")


GROUP_ROWS = (("mem_before_fork", "pss_mib", "source after setup"), ("fork", "pss_mib", "right after fork"),
              ("fork", "pss_anon_mib", "  anon"), ("fork", "pss_file_mib", "  file"), ("group_done", "pss_mib", "after rollouts"),
              ("group_done", "pss_anon_mib", "  anon"), ("group_done", "pss_file_mib", "  file"))


def memory(specs):
    systems = {}  # name -> (runs, {task: {event: totals}}, {task: [rollout errors]})
    for spec in specs:
        name, runs = spec.split("=", 1)
        g, err = {}, collections.defaultdict(list)
        for run in runs.split(","):
            for e in events(run):
                if e["event"] in ("mem_before_fork", "fork", "group_done"):
                    g.setdefault(e["task"], {})[e["event"]] = e["total"]
            for task, tm in rollouts(run):
                err[task].append(tm.get("error"))
        systems[name] = (runs.split(","), g, err)
    tasks = [t for t in next(iter(systems.values()))[1]
             if all(all(k in g.get(t, {}) for k, _, _ in GROUP_ROWS) for _, g, _ in systems.values())]
    clean = [t for t in tasks if not any(any(err.get(t, [])) for _, _, err in systems.values())]
    for title, ts in (("all groups", tasks), ("groups with no failed rollout", clean)):
        print(f"\nPSS per group, GiB ({title}, n={len(ts)})")
        print(f"{'':24s}" + "".join(f"{n:>10s}" for n in systems))
        for ev, key, label in GROUP_ROWS:
            print(f"{label:24s}" + "".join(f"{st.mean(g[t][ev][key] for t in ts) / 1024:10.2f}" for _, g, _ in systems.values()))
    print("\nwhole run (first run of each system)")
    for name, (runs, _, err) in systems.items():
        rows = [json.loads(l) for l in open(Path(runs[0]) / "mem.jsonl")]
        n_err = sum(1 for v in err.values() for x in v if x)
        print(f"  {name:8s} peak PSS {max(r['total']['pss_mib'] for r in rows) / 1024:5.1f} GiB  "
              f"peak host used {max(r['host']['used_delta_mib'] for r in rows) / 1024:5.1f} GiB  "
              f"{(rows[-1]['t'] - rows[0]['t']) / 60:3.0f} min  rollout errors {n_err}")


def clones(run):
    att = clone_attempts(events(run))
    bad = [e for e in att if not e["ok"]]
    per = collections.Counter(e["task"] for e in att)
    print(f"{run}: {len(att)} attempts, {len(bad)} failed, {len({e['task'] for e in bad})} groups retried; "
          f"attempts per group {dict(collections.Counter(per.values()))}")
    reasons = collections.Counter()
    for e in bad:
        lines = "\n".join(e["why"] if isinstance(e["why"], list) else [e["why"]]).splitlines()
        for line in dict.fromkeys(re.sub(r"\d{3,}", "N", l.split("; see ")[0].strip()) for l in lines if "Error" in l):
            reasons[line[:150]] += 1
    for r, n in reasons.most_common(8):
        print(f"  {n:3d}  {r}")


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    {"progress": progress, "memory": memory, "clones": lambda r: clones(r[0])}[cmd](args)
