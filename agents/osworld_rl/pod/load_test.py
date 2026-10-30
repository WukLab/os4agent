"""N concurrent Thinking requests (half Chrome, half Calc prompt), budget B with forced answer, as budget_test.py.
Prints per-request time / tokens / tok/s (median, p90) per app and total throughput."""
import json, statistics as st, sys, time
from concurrent.futures import ThreadPoolExecutor
sys.argv = [sys.argv[0], "qwen3vl8b-think", "1024"] + sys.argv[1:]
import budget_test as bt  # noqa: E402  (its module-level loop runs once: warms the server)

def one(i):
    p = bt.P[i % 2]
    msgs = [dict(m) for m in p["messages"]]
    msgs[0]["content"] = msgs[0]["content"].replace(bt.OLD, bt.NEW)
    t0 = time.time()
    text, n, _ = bt.chat(msgs, bt.B)
    if "</think>" not in text:
        tail, n2, _ = bt.chat(msgs + [{"role": "assistant", "content": text + "\n\nI have thought enough; I'll answer now.\n</think>\n\nThought:"}],
                              300, add_generation_prompt=False, continue_final_message=True)
        text, n = text + tail, n + n2
    return p["name"], time.time() - t0, n, "Action:" in text

for N in (8, 32, 64, 128):
    t0 = time.time()
    with ThreadPoolExecutor(N) as ex:
        res = list(ex.map(one, range(N)))
    wall = time.time() - t0
    for app in ("chrome", "libreoffice_calc"):
        r = [x for x in res if x[0] == app]
        q = lambda v: (st.median(v), sorted(v)[int(0.9 * (len(v) - 1))])
        (tm, t9), (nm, _), (sm, _) = q([x[1] for x in r]), q([x[2] for x in r]), q([x[2] / x[1] for x in r])
        print(f"N={N:3} {app:17} time median {tm:5.1f} s p90 {t9:5.1f} s | out median {nm:5.0f} tok | {sm:4.1f} tok/s per request | actions {sum(x[3] for x in r)}/{len(r)}", flush=True)
    print(f"N={N:3} total {sum(x[2] for x in res) / wall:6.0f} tok/s over {wall:.0f} s", flush=True)
