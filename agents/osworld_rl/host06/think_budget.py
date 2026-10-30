"""Per recording: how often the thinking hit the budget (the agent forced </think>), invalid actions with and without
it, model-call time and output tokens.  python3 think_budget.py DIR ..."""
import glob, json, os, statistics as st, sys
MARK = "I have thought enough; I'll answer now."
for root in sys.argv[1:]:
    n = forced = inv = inv_forced = 0
    lat, toks = [], []
    for f in glob.glob(f"{root}/*/*__g*/chat.jsonl"):
        for c in map(json.loads, open(f)):
            n += 1
            fc = MARK in (c.get("response") or "")
            bad = (c.get("action") or {}).get("action") == "invalid"
            forced += fc
            inv += bad
            inv_forced += bad and fc
            t = c.get("t") or {}
            lat.append(t.get("llm_end", 0) - t.get("llm_start", 0))
            toks.append(c.get("completion_tokens") or 0)
    ev = [json.loads(l) for l in open(f"{root}/events.jsonl")]
    d = [e for e in ev if e["event"] == "rollout_done"]
    t0 = ev[0]["t"]
    print(f"{os.path.basename(root):15s} calls {n}: hit the budget {forced / n:5.1%} | invalid {inv / n:4.1%} "
          f"(when cut off {inv_forced / max(1, forced):4.1%}, else {(inv - inv_forced) / max(1, n - forced):4.1%}) | "
          f"model call median {st.median(lat):4.1f} s, tokens median {st.median(toks):.0f} | solved {sum(e['reward'] > 0 for e in d)} | "
          f"epoch {(max(e['t'] for e in d) - t0) / 60:.1f} min")
