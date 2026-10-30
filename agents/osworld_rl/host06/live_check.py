"""Sanity check of a live --screen-cache recording (no recording to compare with): python3 live_check.py traces/<run>"""
import glob, json, statistics as st, sys
d = sys.argv[1]
ev = [json.loads(l) for l in open(f"{d}/events.jsonl")]
done = [e for e in ev if e["event"] == "rollout_done"]
chk = [e for e in ev if e["event"] == "scache_check"]
kinds = {}
for f in glob.glob(f"{d}/*/*__g*/traj.jsonl"):
    for l in open(f):
        k = json.loads(l).get("skipped") or "normal"
        kinds[k] = kinds.get(k, 0) + 1
chat_lines = sum(1 for f in glob.glob(f"{d}/*/*__g*/chat.jsonl") for _ in open(f))
print(f"elapsed {(ev[-1]['t'] - ev[0]['t']) / 60:.1f} min | rollouts done {len(done)}, solved {sum(e['reward'] > 0 for e in done)}, "
      f"errors {[(e['task'][:8], (e.get('error') or '')[:50]) for e in done if e.get('error')]}")
print(f"steps {kinds} | chat.jsonl lines {chat_lines} (should equal the steps) | checks {len(chk)}: ok {sum(e['ok'] for e in chk)}, "
      f"rejected {sum(not e['ok'] for e in chk)}" + (f", model waited median {st.median(e['waited_s'] for e in chk):.1f} s" if chk else ""))
print("group errors", [e["error"][:120] for e in ev if e["event"] == "group_error"])
