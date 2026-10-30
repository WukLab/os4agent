"""128 concurrent requests (different real prompts, 1024 tokens each, ignore_eos), while sampling vLLM /metrics every 2 s.
Reports generation tokens/s over the samples where all requests are running (none waiting). python decode_tps.py MODEL [N]"""
import json, random, re, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
MODEL, N = sys.argv[1], int(sys.argv[2]) if sys.argv[2:] else 128
P = [json.loads(l) for l in open("/root/think_prompts.jsonl")]
random.Random(0).shuffle(P)

def metrics():
    t = urllib.request.urlopen("http://localhost:8000/metrics", timeout=10).read().decode()
    g = lambda name: sum(float(v) for v in re.findall(rf"^{name}(?:{{[^}}]*}})? ([0-9.e+]+)$", t, re.M))
    return time.time(), g("vllm:generation_tokens_total"), g("vllm:num_requests_running"), g("vllm:num_requests_waiting")

samples, stop = [], threading.Event()
def sampler():
    while not stop.is_set():
        samples.append(metrics())
        time.sleep(2)

def one(i):
    body = json.dumps({"model": MODEL, "messages": P[i % len(P)], "max_tokens": 1024, "ignore_eos": True,
                       "temperature": 1.0, "top_p": 0.9}).encode()
    urllib.request.urlopen(urllib.request.Request("http://localhost:8000/v1/chat/completions", body, {"Content-Type": "application/json"}), timeout=3600).read()

th = threading.Thread(target=sampler, daemon=True); th.start()
t0 = time.time()
with ThreadPoolExecutor(N) as ex:
    list(ex.map(one, range(N)))
stop.set(); th.join()
full = [(a, b) for a, b in zip(samples, samples[1:]) if a[2] >= N and b[2] >= N and a[3] == 0 and b[3] == 0]
tps = [(b[1] - a[1]) / (b[0] - a[0]) for a, b in full]
peak_run = max(s[2] for s in samples)
print(f"{MODEL}: wall {time.time() - t0:.0f} s, max running {peak_run:.0f}, max waiting {max(s[3] for s in samples):.0f}; "
      + (f"all {N} decoding for {sum(b[0] - a[0] for a, b in full):.0f} s: {sum(tps) / len(tps):.0f} tok/s total, {sum(tps) / len(tps) / N:.1f} tok/s per request"
         if tps else f"never had all {N} running at once"), flush=True)
