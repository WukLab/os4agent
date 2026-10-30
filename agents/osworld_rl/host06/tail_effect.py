"""Did speculation shorten the tail? Per run: when the 64th / last rollout finished, tail length, and in the tail
(after < 64 live) the per-step time after the model answered: hits vs normal steps."""
import glob, json, statistics as st, sys
med = lambda v: f"{st.median(v):5.1f}" if v else "    -"
for r in sys.argv[1:]:
    ev = [json.loads(l) for l in open(f"traces/{r}/events.jsonl")]
    t0 = ev[0]["t"]
    done = sorted(e["t"] for e in ev if e["event"] == "rollout_done")
    t64 = done[63] if len(done) > 63 else None
    steps = []
    for f in glob.glob(f"traces/{r}/*/*/traj.jsonl"):
        chat = [json.loads(l) for l in open(f.replace("traj.jsonl", "chat.jsonl"))]
        for i, s in enumerate(json.loads(l) for l in open(f) if l.strip()):
            if i < len(chat) and "exec_s" in s:
                steps.append((chat[i]["t"]["llm_end"], s.get("skipped") == "spec", s["exec_s"], chat[i]["t"]["llm_end"] - chat[i]["t"]["llm_start"]))
    tail = [s for s in steps if t64 and s[0] > t64 - 0]  # steps whose model call ended after the batch dropped below 64
    sp = [e for e in ev if e["event"] == "spec_exec"]
    print(f"{r}: 64th done {(t64 - t0) / 60:.1f} min, last {(done[-1] - t0) / 60:.1f} min -> tail {(done[-1] - t64) / 60:.1f} min")
    print(f"   tail steps {len(tail)}: hits {sum(s[1] for s in tail)}; env time after the model: hit {med([s[2] for s in tail if s[1]])} s, "
          f"normal {med([s[2] for s in tail if not s[1]])} s; model {med([s[3] for s in tail])} s")
    if sp:
        print(f"   speculation: {len(sp)} steps, {sum(e['hit'] is not None for e in sp)} hits, fork {med([e['fork_s'] for e in sp if e['fork_s'] > 0])} s, "
              f"wait on hit {med([e['waited_s'] for e in sp if e['hit'] is not None])} s, errors {sum(bool(e['error']) for e in sp)}")
