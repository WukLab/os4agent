"""Summarize a wa_replay.py run: fidelity against the recording (page rows, acted-on row, URL after each action,
reward), step time split replayed vs recorded, fork time, and memory from the cgroups.
  python3 replay_report.py /mnt/data/btrfs/wa_replay/<run>"""
import json, statistics as st, sys
from pathlib import Path

R = Path(sys.argv[1])
res = [json.loads(p.read_text()) for p in sorted(R.glob("*__g*/result.json"))]
steps = [json.loads(l) for p in sorted(R.glob("*__g*/steps.jsonl")) for l in open(p) if l.strip()]
med = lambda xs: round(st.median(xs), 2) if xs else None
frac = lambda xs: f"{sum(map(bool, xs))}/{len(xs)}" if xs else "-"

print(f"## {R.name}: {len(res)} rollouts, {len(steps)} steps")
print(f"- errors: {sum(1 for r in res if r.get('error'))}; reward same as recorded: "
      f"{frac([r.get('reward') == r.get('reward_rec') for r in res])}; reward sum now {sum(r.get('reward') or 0 for r in res)}"
      f" vs recorded {sum(r.get('reward_rec') or 0 for r in res)}")
print(f"- page rows identical: {frac([s['rows_equal'] for s in steps])}; same row count: "
      f"{frac([s['rows_rec'] == s['rows_now'] for s in steps])}; acted-on row same: "
      f"{frac([s['target_equal'] for s in steps if s['target_equal'] is not None])}; URL after action same: "
      f"{frac([s['url_after_equal'] for s in steps if 'url_after_equal' in s])}")
first = [s for s in steps if s["step"] == 1]
print(f"- step 1 (right after the fork) rows identical: {frac([s['rows_equal'] for s in first])}")
err_now = sum(1 for s in steps if s.get("error"))
err_rec = sum(1 for s in steps if (s.get("rec") or {}).get("error"))
ev = [json.loads(l) for l in open(R / "events.jsonl")] if (R / "events.jsonl").exists() else []
cf = [e for e in ev if e["event"] == "clone_failed"]
cd = [e for e in ev if e["event"] == "clone_done"]
print(f"- clones: {len(cd)} succeeded, {sum(e.get('attempt', 0) > 0 for e in cd)} of them only after a retry; "
      f"{len(cf)} failed attempts in all (clone_fail/); groups lost: "
      f"{sum(e.get('failed', 0) for e in ev if e['event'] == 'wave_setup_done')}")
redo = [r for r in res if "redo" in str(r.get("trace", ""))]
print(f"- rollouts replayed from the re-recorded (redo) traces: {len(redo)} "
      f"({', '.join(sorted(Path(r['trace']).name for r in redo))})")
rm = [s["remapped"] for s in steps if "remapped" in s]
print(f"- element ids remapped: {len(rm)} ({sum(r[1] is None for r in rm)} with no matching row)")
print(f"- action errors now {err_now} vs recorded {err_rec}")

print("\n| per step, median s | replay | recorded |\n|---|---|---|")
for lab, a0, a1 in (("observe (page read)", "t_obs_start", "t_obs_end"), ("model (slept / real)", "t_llm_send", "t_llm_done"),
                    ("action", "t_act_start", "t_act_end"), ("settle", "t_act_end", "t_settle_end")):
    now = [s[a1] - s[a0] for s in steps if s.get(a1) and s.get(a0)]
    rec = [s["rec"][a1] - s["rec"][a0] for s in steps if s["rec"].get(a1) and s["rec"].get(a0)]
    print(f"| {lab} | {med(now)} (sum {round(sum(now))}) | {med(rec)} (sum {round(sum(rec))}) |")

for p in sorted(R.glob("src_*.json")):
    s = json.loads(p.read_text())
    f, t = s["fork"], s["setup"]
    print(f"- {s['src']}: setup {t['t_ready'] - t['t_start']:.1f} s, clone {f['t_clone_end'] - f['t_clone_start']:.1f} s, "
          f"fixup {f['t_fixup_end'] - f['t_clone_end']:.1f} s, {len(s['copies'])} copies")

mem = [json.loads(l) for l in open(R / "mem.jsonl")]
if mem:
    pk = max(mem, key=lambda m: m["total"].get("cg_mib", 0))
    print(f"\nmemory at the peak sample ({pk['envs']} envs, {pk['total'].get('distinct_cgroups')} distinct cgroups), MiB:")
    print("| | current | ws (current - inactive_file) | anon | file | active_file | inactive_file | shmem | PSS |\n|---|---|---|---|---|---|---|---|---|")
    g = lambda d: [d.get(k) for k in ("cg_mib", "cg_ws_mib", "cg_anon_mib", "cg_file_mib", "cg_active_file_mib",
                                      "cg_inactive_file_mib", "cg_shmem_mib")]
    print("| sum of env cgroups |", " | ".join(map(str, g(pk["total"]))), f"| {pk['total'].get('pss_mib')} |")
    if pk.get("parent"):
        print(f"| parent {pk['parent']['cg']} |", " | ".join(map(str, g(pk["parent"]))), "| |")
    for role in ("src", "copy"):
        cs = [c for c in pk["containers"].values() if c["role"] == role]
        if cs:
            print(f"| {role} (median of {len(cs)}) |", " | ".join(str(med([c.get(k) or 0 for c in cs])) for k in
                  ("cg_mib", "cg_ws_mib", "cg_anon_mib", "cg_file_mib", "cg_active_file_mib", "cg_inactive_file_mib",
                   "cg_shmem_mib")), f"| {med([c['pss_mib'] for c in cs])} |")
    print(f"- host used (MemTotal - MemAvailable) at that sample: {pk['host']['used_mib']} MiB (reference only)")
