"""Status of the Thinking GRPO runs: python3 think_status.py [exp ...] (default grpo_think_reg grpo_think_spec).
Per epoch: state, wall time, rollouts, reward, model latency, speculation, clone failures, peak memory, saved adapter."""
import glob, json, os, statistics as st, sys, time

med = lambda v: f"{st.median(v):.1f}" if v else "-"


def epoch(d):
    ev = [json.loads(l) for l in open(f"{d}/events.jsonl")] if os.path.exists(f"{d}/events.jsonl") else []
    if not ev:
        return None
    t0, end = ev[0]["t"], next((e["t"] for e in ev if e["event"] == "run_done"), None)
    done = [e for e in ev if e["event"] == "rollout_done"]
    planned = 8 * sum(1 for e in ev if e["event"] == "fork") or len(glob.glob(f"{d}/*/*__g*"))
    rew = [e["reward"] for e in done]
    chat = [json.loads(l) for f in glob.glob(f"{d}/*/*/chat.jsonl") for l in open(f)]
    lat = [c["t"]["llm_end"] - c["t"]["llm_start"] for c in chat]
    sp = [e for e in ev if e["event"] == "spec_exec"]
    clones = [e for e in ev if e["event"] == "tfork_clone"]
    why = lambda e: " ".join(e["why"]) if isinstance(e.get("why"), list) else str(e.get("why") or "")
    bad = [e for e in clones if not e["ok"]]
    mem = [json.loads(l) for l in open(f"{d}/mem.jsonl")] if os.path.exists(f"{d}/mem.jsonl") else []
    peak = lambda k: max((m["total"].get(k, 0) for m in mem), default=0) / 1024
    host = max((m["host"]["used_delta_mib"] for m in mem), default=0) / 1024
    return {
        "state": "done" if end else "running", "min": ((end or time.time()) - t0) / 60,
        "rollouts": f"{len(done)}/{planned}", "errors": sum(bool(e.get("error")) for e in done),
        "reward": (f"{sum(r > 0 for r in rew)} ok / {planned} (mean so far {st.mean(rew):.3f}, biased up mid-epoch: successes finish first)"
                   if not end and rew else f"{st.mean(rew):.3f} ({sum(r > 0 for r in rew)} ok / {len(rew)})" if rew else "-"),
        "model_s": med(lat), "forced": f"{100 * sum('I have thought enough' in c['response'] for c in chat) / max(len(chat), 1):.0f}%",
        "invalid": f"{100 * sum(c['action'].get('action') == 'invalid' for c in chat) / max(len(chat), 1):.0f}%",
        "spec": (f"{len(sp)} steps, {sum(e['hit'] is not None for e in sp)} hits, fork {med([e['fork_s'] for e in sp if e['fork_s'] > 0])} s, "
                 f"hit wait {med([e['waited_s'] for e in sp if e['hit'] is not None])} s") if sp else "off",
        "clone_fail": f"{len(bad)}/{len(clones)} ({sum('resolve parent' in why(e) for e in bad)} cascade)",
        "mem_peak": f"ws {peak('cg_ws_mib'):.1f} / cgroup {peak('cg_mib'):.1f} / pss {peak('pss_mib'):.1f} / host+ {host:.1f} GiB",
    }


for exp in sys.argv[1:] or ["grpo_think_reg", "grpo_think_spec"]:
    loop = {}
    p = f"pod_backup/{exp}/{exp}_loop.jsonl"
    for l in (open(p) if os.path.exists(p) else []):
        r = json.loads(l)
        loop[r["epoch"]] = r
    print(f"== {exp}")
    for d in sorted((x for x in glob.glob(f"traces/{exp}_e[0-9]*") if os.path.isdir(x)), key=lambda x: int(x.rsplit("_e", 1)[1])):
        n = int(d.rsplit("_e", 1)[1])
        s = epoch(d)
        if not s:
            print(f"  e{n}: starting")
            continue
        r = loop.get(n, {})
        train = f"trained {r['train_secs']:.0f} s -> {os.path.relpath(r['adapter'])}" if r.get("adapter") else (r.get("skipped") or "not trained yet")
        print(f"  e{n} [{s['state']}] {s['min']:.1f} min | rollouts {s['rollouts']}, errors {s['errors']} | reward {s['reward']}")
        print(f"      model {s['model_s']} s median, forced {s['forced']}, invalid {s['invalid']} | spec: {s['spec']} | clone fail {s['clone_fail']}")
        print(f"      peak {s['mem_peak']} | {train}")
