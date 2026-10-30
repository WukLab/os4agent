import json, glob
p = glob.glob("traces/shot6_shot/vlc/bba3381f*__g0/chat.jsonl")[0]
for i, l in enumerate(open(p)):
    if i + 1 < 6:
        continue
    x = json.loads(l)
    j = x["action"].get("id")
    tgt = x["rows"][j][1] if isinstance(j, int) and 0 <= j < len(x["rows"]) else ""
    ans = x["response"].rsplit("</think>", 1)[-1].strip().replace("\n", " ")
    print(f"step {i + 1}: {x['action']} -> {tgt!r}\n   {ans[:420]}\n")
