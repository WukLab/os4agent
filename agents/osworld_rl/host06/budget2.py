"""Thinking-budget overruns and invalid actions: python3 budget2.py NAME=TRACE:BUDGET ..."""
import glob, json, statistics as st, sys
for arg in sys.argv[1:]:
    name, rest = arg.split("=", 1)
    d, budget = rest.rsplit(":", 1)
    budget = int(budget)
    n = over = inv = 0; toks = []; solved = done = 0
    for f in glob.glob(f"{d}/*/*__g*/chat.jsonl"):
        for c in map(json.loads, open(f)):
            if "completion_tokens" not in c:
                continue
            n += 1; toks.append(c["completion_tokens"]); over += c["completion_tokens"] >= budget
            inv += (c.get("action") or {}).get("action") == "invalid"
    for r in glob.glob(f"{d}/*/*__g*/result.txt"):
        done += 1; solved += float(open(r).read()) > 0
    print(f"{name}: solved {solved}/{done} | calls {n}, median output tokens {st.median(toks) if toks else 0:.0f}, "
          f"over its {budget}-token budget {over} ({over / max(1, n):.0%}), invalid actions {inv}")
