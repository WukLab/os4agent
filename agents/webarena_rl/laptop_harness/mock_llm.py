"""Scripted stand-in for vLLM (OpenAI chat API) to smoke-test the env side without a GPU:  python mock_llm.py [port]
Plays a fixed 3-step script per rollout (keyed by the x-task header): go to the Canon-printer search, scroll, then answer NAVIGATE/SUCCESS.
Correct for task 326, so a working pipeline should score 1.0 there and 0.0 elsewhere."""
import http.server, json, re, sys, urllib.parse
step = {}

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(s): s.reply({"data": [{"id": "mock"}]})
    def do_POST(s):
        body = json.loads(s.rfile.read(int(s.headers.get("content-length", 0))))
        user = body["messages"][-1]["content"]; key = s.headers.get("x-task", "")
        n = step[key] = step.get(key, 0) + 1
        origin = re.search(r"Current URL: (https?://[^/\s]+)", user).group(1)
        acts = [{"action": "goto", "url": origin + "/catalogsearch/result/?" + urllib.parse.urlencode({"q": "Canon photo printer"})},
                {"action": "scroll", "direction": "down"},
                {"action": "done", "answer": {"task_type": "NAVIGATE", "status": "SUCCESS", "retrieved_data": None, "error_details": None}}]
        text = f"Thought: scripted step {n}.\nAction: {json.dumps(acts[min(n, 3) - 1])}"
        s.reply({"id": "x", "object": "chat.completion", "model": body.get("model"), "choices": [{"index": 0, "finish_reason": "stop",
                 "message": {"role": "assistant", "content": text}}], "usage": {"prompt_tokens": len(user) // 4, "completion_tokens": 30, "total_tokens": 0}})
    def reply(s, o):
        b = json.dumps(o).encode(); s.send_response(200); s.send_header("Content-Type", "application/json"); s.send_header("Content-Length", str(len(b)))
        s.end_headers(); s.wfile.write(b)
    def log_message(s, *a): pass

http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8000), H).serve_forever()
