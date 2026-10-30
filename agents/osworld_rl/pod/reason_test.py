"""On the pod: send the 2 recorded prompts, short (as recorded) and with the A11Y_REASON system prompt; one request at a
time, then both at once. Prints output tokens, time, tokens/s and the Action line."""
import json, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

MODEL, MAX = sys.argv[1], int(sys.argv[2]) if sys.argv[2:] else 1024
P = json.load(open("/root/reason_prompts.json"))
OLD, NEW = "Reply with a one-sentence Thought, then ONE line", "Think step by step in a Thought as long as you need, then end with ONE line"

def ask(p, reason):
    msgs = [dict(m) for m in p["messages"]]
    if reason:
        msgs[0]["content"] = msgs[0]["content"].replace(OLD, NEW)
    body = json.dumps({"model": MODEL, "messages": msgs, "max_tokens": MAX if reason else 300, "temperature": 1.0, "top_p": 0.9}).encode()
    t0 = time.time()
    r = json.load(urllib.request.urlopen(urllib.request.Request("http://localhost:8000/v1/chat/completions", body, {"Content-Type": "application/json"}), timeout=600))
    dt = time.time() - t0
    text, u = r["choices"][0]["message"]["content"] or "", r["usage"]
    act = text[text.rfind("Action:"):].split("\n")[0] if "Action:" in text else "NO ACTION"
    return f"{p['name']:17} {'reason' if reason else 'short ':6} prompt {u['prompt_tokens']:5} out {u['completion_tokens']:5} tok  {dt:5.1f} s  {u['completion_tokens']/dt:5.1f} tok/s  " \
           f"finish={r['choices'][0]['finish_reason']}  {act[:70]}", text

for reason in (False, True):
    for p in P:
        line, text = ask(p, reason)
        print(line, flush=True)
        if reason:
            open(f"/root/out_{MODEL}_{p['name']}.txt", "w").write(text)
print("-- both reasoning requests at once")
with ThreadPoolExecutor(2) as ex:
    for line, _ in ex.map(lambda p: ask(p, True), P):
        print(line, flush=True)
