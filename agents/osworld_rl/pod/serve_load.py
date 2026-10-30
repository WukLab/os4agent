"""N concurrent Thinking requests from N different recorded GRPO prompts (budget 1024, no forcing): per-request
latency and total generation throughput. python serve_load.py MODEL [N]"""
import json, random, statistics as st, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
MODEL, N = sys.argv[1], int(sys.argv[2]) if sys.argv[2:] else 128
P = [json.loads(l) for l in open("/root/think_prompts.jsonl")]
random.Random(0).shuffle(P)
def one(i):
    body = json.dumps({"model": MODEL, "messages": P[i % len(P)], "max_tokens": 1024, "temperature": 1.0, "top_p": 0.9}).encode()
    t0 = time.time()
    r = json.load(urllib.request.urlopen(urllib.request.Request("http://localhost:8000/v1/chat/completions", body, {"Content-Type": "application/json"}), timeout=1800))
    return time.time() - t0, r["usage"]["completion_tokens"], r["usage"]["prompt_tokens"]
t0 = time.time()
with ThreadPoolExecutor(N) as ex:
    res = list(ex.map(one, range(N)))
wall = time.time() - t0
lat = [x[0] for x in res]
print(f"{MODEL} N={N}: latency median {st.median(lat):.1f} s p90 {sorted(lat)[int(.9 * (N - 1))]:.1f} s, out tokens median {st.median(x[1] for x in res):.0f}, "
      f"prompt median {st.median(x[2] for x in res):.0f}, total gen throughput {sum(x[1] for x in res) / wall:.0f} tok/s, wall {wall:.0f} s", flush=True)
