"""Greedy answers to 8 fixed prompts: python greedy.py MODEL OUT.json"""
import json, sys, urllib.request
P = [json.loads(l) for l in open("/root/think_prompts.jsonl")][:8]
out = []
for m in P:
    body = json.dumps({"model": sys.argv[1], "messages": m, "max_tokens": 96, "temperature": 0}).encode()
    r = json.load(urllib.request.urlopen(urllib.request.Request("http://localhost:8000/v1/chat/completions", body, {"Content-Type": "application/json"}), timeout=600))
    out.append(r["choices"][0]["message"]["content"])
json.dump(out, open(sys.argv[2], "w"))
print(f"{sys.argv[1]}: {len(out)} answers")
