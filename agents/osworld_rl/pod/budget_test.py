"""Thinking budget: think up to B tokens; if </think> hasn't come, close it and continue the same assistant message so
the model must answer. Prints tokens, time and the Action for each prompt."""
import json, sys, time, urllib.request

MODEL, B = sys.argv[1], int(sys.argv[2])
P = json.load(open("/root/reason_prompts.json"))
OLD, NEW = "Reply with a one-sentence Thought, then ONE line", "Think step by step in a Thought as long as you need, then end with ONE line"

def chat(msgs, max_tokens, **kw):
    body = json.dumps({"model": MODEL, "messages": msgs, "max_tokens": max_tokens, "temperature": 1.0, "top_p": 0.9, **kw}).encode()
    r = json.load(urllib.request.urlopen(urllib.request.Request("http://localhost:8000/v1/chat/completions", body,
                                                                  {"Content-Type": "application/json"}), timeout=600))
    return r["choices"][0]["message"]["content"] or "", r["usage"]["completion_tokens"], r["choices"][0]["finish_reason"]

for p in P:
    msgs = [dict(m) for m in p["messages"]]
    msgs[0]["content"] = msgs[0]["content"].replace(OLD, NEW)
    t0 = time.time()
    text, n, fin = chat(msgs, B)
    forced = ""
    if "</think>" not in text:  # over budget: close the thinking and make it answer
        head = text + "\n\nI have thought enough; I'll answer now.\n</think>\n\nThought:"
        tail, n2, fin = chat(msgs + [{"role": "assistant", "content": head}], 300,
                             add_generation_prompt=False, continue_final_message=True)
        text, n, forced = head + tail, n + n2, " (forced)"
    act = text[text.rfind("Action:"):].split("\n")[0] if "Action:" in text else "NO ACTION"
    print(f"{p['name']:17} budget {B}: out {n:5} tok  {time.time() - t0:5.1f} s{forced:9} finish={fin}  {act[:80]}", flush=True)
    open(f"/root/budget_{B}_{p['name']}.txt", "w").write(text)
