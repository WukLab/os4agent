"""Summarize osw_run.py profiling runs:  python prof_summary.py <run_dir> [<run_dir> ...]
Per task: source PSS before fork, total PSS right after fork, peak container PSS and host-used during rollouts,
fork timings (CRIU checkpoint/image/restores or tfork clone), rollout steps and rewards. Plus run totals and TAGE hit rates."""
import json, statistics as st, sys
from collections import defaultdict
from pathlib import Path

G = lambda mib: f"{mib / 1024:.2f}"


def summarize(run):
    run = Path(run)
    ev = [json.loads(l) for l in open(run / "events.jsonl")]
    mem = [json.loads(l) for l in open(run / "mem.jsonl")]
    order, by = [], defaultdict(dict)
    for r in ev:
        t = r.get("task")
        if not t: continue
        if t not in by: order.append(t)
        d = by[t]; e = r["event"]
        if e == "mem_before_fork": d["src"] = r["total"]["pss_mib"]
        elif e == "criu_checkpoint": d["ckpt_s"], d["img_mib"] = r["secs"], r["image_mib"]
        elif e in ("criu_restore", "ckpt_clone"): d.setdefault("restore_s", []).append(r["secs"])   # per-copy restore (CKPT: dump+restore)
        elif e == "tfork_clone": d.setdefault("clone", []).append((r["ok"], r["secs"]))
        elif e == "checkpoint_saved": d["saved_mib"] = r["mib"]
        elif e == "fork": d["fork_s"], d["after_fork"], d["anon_after"] = r["secs"], r["total"]["pss_mib"], r["total"]["pss_anon_mib"]
        elif e == "rollout_done": d.setdefault("steps", []).append(r["steps"]); d.setdefault("rew", []).append(r["reward"])
        elif e == "group_error": d["error"] = r["error"][:120]
    # peak during each task's rollout phase (phase "t<i>:rollouts")
    peak = defaultdict(lambda: [0, 0, 0])
    for m in mem:
        if "phases" in m:   # per-group phases (task groups may run in parallel); containers carry their group index "t"
            for ti, ph in m["phases"].items():
                if ph != "rollouts": continue
                p = peak[f"t{ti}"]; grp = sum(c["pss_mib"] for c in m["containers"].values() if str(c.get("t")) == str(ti))
                p[0] = max(p[0], grp); p[1] = max(p[1], m["host"]["used_mib"]); p[2] = max(p[2], m["cpu"]["user"] + m["cpu"]["sys"])
        elif m["phase"].endswith(":rollouts"):   # older runs: one group at a time
            p = peak[m["phase"].split(":")[0]]
            p[0] = max(p[0], m["total"]["pss_mib"]); p[1] = max(p[1], m["host"]["used_mib"]); p[2] = max(p[2], m["cpu"]["user"] + m["cpu"]["sys"])
    whole = max((m["total"]["pss_mib"] for m in mem), default=0); hostmax = max((m["host"]["used_mib"] for m in mem), default=0)
    whole_cg = max((m["total"].get("cg_mib", 0) for m in mem), default=0)
    host_delta = max((m["host"].get("used_delta_mib", 0) for m in mem), default=0)
    cgpeak = defaultdict(int)
    for m in mem:
        for ti, ph in (m.get("phases") or {}).items():
            cgpeak[f"t{ti}"] = max(cgpeak[f"t{ti}"], sum(c.get("cg_mib", 0) for c in m["containers"].values() if str(c.get("t")) == str(ti)))
    print(f"\n== {run.name}")
    print(f"{'task':9} {'src GiB':>7} {'+fork GiB':>9} {'anon':>6} {'peak GiB':>8} {'cg pk':>6} {'host GiB':>8} {'cpu%':>5} | {'fork s':>6} {'ckpt s':>6} {'img GiB':>7} {'restore s':>9} | {'steps':>5} {'reward':>6}")
    tot = defaultdict(list)
    for i, t in enumerate(order):
        d = by[t]; pk = peak.get(f"t{i}", [0, 0, 0])
        rs = d.get("restore_s") or []
        print(f"{t[:8]:9} {G(d.get('src', 0)):>7} {G(d.get('after_fork', 0)):>9} {G(d.get('anon_after', 0)):>6} {G(pk[0]):>8} {G(cgpeak.get(f't{i}', 0)):>6} {G(pk[1]):>8} {100 * pk[2]:>5.0f} | "
              f"{d.get('fork_s', 0):>6.1f} {d.get('ckpt_s', 0):>6.1f} {G(d.get('img_mib', 0)):>7} {(st.mean(rs) if rs else 0):>9.1f} | "
              f"{(st.mean(d['steps']) if d.get('steps') else 0):>5.1f} {(st.mean(d['rew']) if d.get('rew') else 0):>6.2f}" + (f"  ERROR {d['error']}" if d.get("error") else ""))
        for k, v in (("src", d.get("src")), ("after", d.get("after_fork")), ("peak", pk[0]), ("host", pk[1]), ("fork", d.get("fork_s"))):
            if v: tot[k].append(v)
        tot["rew"] += d.get("rew", []); tot["steps"] += d.get("steps", [])
    if tot["after"]:
        print(f"{'mean':9} {G(st.mean(tot['src'])):>7} {G(st.mean(tot['after'])):>9} {'':>6} {G(st.mean(tot['peak'])):>8} {'':>6} {G(st.mean(tot['host'])):>8} {'':>5} | "
              f"{st.mean(tot['fork']):>6.1f} {'':>6} {'':>7} {'':>9} | {st.mean(tot['steps']):>5.1f} {st.mean(tot['rew']):>6.3f}")
        print(f"all environments at once: peak PSS {G(whole)} GiB, peak cgroup charge {G(whole_cg)} GiB; host used peak {G(hostmax)} GiB "
              f"(+{G(host_delta)} GiB over the run-start baseline)")
        print(f"max group PSS {G(max(tot['peak']))} GiB; "
              f"rollouts {len(tot['rew'])}, successes {sum(r > 0 for r in tot['rew'])}")
    sp = run / "spec_summary.json"
    if sp.exists():
        s = json.load(open(sp)); k = [x for x in s if x.startswith("hit") and x.endswith("_pct") and x != "hit1_pct"][0]
        print(f"TAGE: {s['decisions']} actions, hit@1 {s['hit1_pct']:.1f}%, {k[:-4]} {s[k]:.1f}%, new-action hit@1 {s['new_hit1_pct']:.1f}% ({s['new']} new)")


if __name__ == "__main__":
    for r in sys.argv[1:]: summarize(r)
