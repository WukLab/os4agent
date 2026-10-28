"""Tracing reverse proxy on 02: agent -> :PROXY_PORT -> (ssh -R tunnel) -> vLLM on RunPod.
Logs every LLM request (t_start/t_first_byte/t_end, sizes, vLLM batch size from /metrics) to traces/llm.jsonl.
Also samples vLLM /metrics every 1s to traces/vllm_metrics.jsonl (running/waiting reqs) for batch-size timelines."""
import http.server, json, os, re, socketserver, sys, threading, time, urllib.request
UP = f"http://127.0.0.1:{os.environ.get('LLM_PORT', 8000)}"; OUT = sys.argv[1]; lock = threading.Lock()
def log(f, r):
    with lock, open(f"{OUT}/{f}", "a") as o: o.write(json.dumps(r) + "\n")
def metrics():
    try:
        t = urllib.request.urlopen(UP + "/metrics", timeout=2).read().decode()
        g = lambda n: float(m.group(1)) if (m := re.search(rf"^{n}(?:\{{[^}}]*\}})? ([0-9.e+-]+)", t, re.M)) else None
        return {"running": g("vllm:num_requests_running"), "waiting": g("vllm:num_requests_waiting"), "kv": g("vllm:kv_cache_usage_perc")}
    except Exception: return {}
def sampler():
    while True: log("vllm_metrics.jsonl", {"t": time.time(), **metrics()}); time.sleep(1)
class H(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def do_GET(s): s.fwd(b"")
    def do_POST(s): s.fwd(s.rfile.read(int(s.headers.get("content-length", 0))))
    def fwd(s, body):
        t0 = time.time(); m0 = metrics(); rq = urllib.request.Request(UP + s.path, body or None, method=s.command,
            headers={k: v for k, v in s.headers.items() if k.lower() not in ("host", "content-length")})
        tf, n, resp = None, 0, b''
        try:
            r = urllib.request.urlopen(rq, timeout=900); s.send_response(r.status)
            for k, v in r.headers.items():
                if k.lower() not in ("transfer-encoding", "connection", "content-length"): s.send_header(k, v)
            s.send_header("Transfer-Encoding", "chunked"); s.end_headers()
            while c := r.read1(65536):
                tf = tf or time.time(); n += len(c); resp += c[:1<<20]; s.wfile.write(b"%x\r\n%s\r\n" % (len(c), c)); s.wfile.flush()
            s.wfile.write(b"0\r\n\r\n"); st = r.status
        except Exception as e: st = repr(e)
        j = json.loads(body) if body[:1] == b"{" else {}
        log("llm.jsonl", {"path": s.path, "task": s.headers.get("x-task"), "t_start": t0, "t_first": tf, "t_end": time.time(),
            "status": st, "req_bytes": len(body), "resp_bytes": n, "n_msgs": len(j.get("messages", [])), "max_tokens": j.get("max_tokens"),
            "metrics_at_start": m0, "resp": resp.decode(errors="replace"), "body": j if os.environ.get("LOG_BODY", "1") == "1" else None})
    def log_message(s, *a): pass
threading.Thread(target=sampler, daemon=True).start()
class S(socketserver.ThreadingMixIn, http.server.HTTPServer): daemon_threads = True
S(("127.0.0.1", int(os.environ.get("PROXY_PORT", 8001))), H).serve_forever()
