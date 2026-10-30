"""wa_replay.py: log each step's page rows and final action (--log-rows), and let --screen-warm read replay dirs."""
s = open("wa_replay.py").read()


def rep(old, new, cnt=1):
    global s
    assert s.count(old) == cnt, (s.count(old), old[:70])
    s = s.replace(old, new)


rep('''ap.add_argument("--screen-warm", default="", help="comma-separated earlier trace dirs (chat.jsonl) the screen cache learns first")''',
'''ap.add_argument("--screen-warm", default="", help="comma-separated earlier trace dirs (chat.jsonl) or replay dirs run with "
                "--log-rows (steps.jsonl) the screen cache learns first")
ap.add_argument("--log-rows", type=int, default=0, help="1: steps.jsonl keeps each step's page rows and final action (for "
                "--screen-warm of a later run)")''')

rep('''            ch = [json.loads(l) for l in open(f) if l.strip()]
            t = int(d.name.split("__g")[0])
            for i in range(len(ch) - 1):
                k = sc_key(t, ch[i]["rows"], ch[i]["action"])
                if k:
                    SC.setdefault(k, ch[i + 1]["rows"])
                    n += 1''', '''            t = int(d.name.split("__g")[0])
            if f.exists():  # a recording: chat.jsonl rows + action
                ch = [(c["rows"], c["action"]) for c in (json.loads(l) for l in open(f) if l.strip())]
            elif (d / "steps.jsonl").exists():  # a replay run with --log-rows: the rows it read, the action it ran
                ch = [(x["rows"], x["act_final"]) for x in (json.loads(l) for l in open(d / "steps.jsonl") if l.strip())
                      if "rows" in x and "act_final" in x]
            else:
                continue
            for i in range(len(ch) - 1):
                k = sc_key(t, ch[i][0], ch[i][1])
                if k:
                    SC.setdefault(k, ch[i + 1][0])
                    n += 1''')

rep('''            f = d / "chat.jsonl"
            if not f.exists():
                continue
''', '''            f = d / "chat.jsonl"
''')

rep('''            s["llm_rec_s"] = c["t"]["llm_end"] - c["t"]["llm_start"]''', '''            if a.log_rows:
                s["rows"], s["act_final"] = rows, act
            s["llm_rec_s"] = c["t"]["llm_end"] - c["t"]["llm_start"]''')
open("wa_replay.py", "w").write(s)
print("patched")
