"""N real prompts with the run's budget logic (1024 thinking, forced answer): how many give a valid Action? python act_check.py MODEL N"""
import json, re, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
MODEL, N = sys.argv[1], int(sys.argv[2])
P = [json.loads(l) for l in open("/root/think_prompts.jsonl")][-N:]
CLOSE = "\n\nI have thought enough; I'll answer now.\n</think>\n\nThought:"
def chat(msgs, mt, **kw):
    body = json.dumps({"model": MODEL, "messages": msgs, "max_tokens": mt, "temperature": 1.0, "top_p": 0.9, **kw}).encode()
    return json.load(urllib.request.urlopen(urllib.request.Request("http://localhost:8000/v1/chat/completions", body, {"Content-Type": "application/json"}), timeout=1800))["choices"][0]["message"]["content"] or ""
def one(m):
    m = [dict(x) for x in m]
    m[0]["content"] = m[0]["content"].replace("Reply with a one-sentence Thought, then ONE line", "Think step by step in a Thought as long as you need, then end with ONE line")
    t = chat(m, 1024)
    if "</think>" not in t:
        t += CLOSE + chat(m + [{"role": "assistant", "content": t + CLOSE}], 300, add_generation_prompt=False, continue_final_message=True)
    ans = t.rsplit("</think>", 1)[-1]
    i = ans.rfind("Action:")
    ok = i >= 0 and re.search(r"\{.*\}", ans[i:]) is not None
    return ok, ("�" in t or "!!!!!!!!" in t)
with ThreadPoolExecutor(N) as ex:
    r = list(ex.map(one, P))
print(f"{MODEL}: valid Action {sum(x[0] for x in r)}/{N}, garbage-looking outputs {sum(x[1] for x in r)}")
