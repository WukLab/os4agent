"""Screen the model saw at each step of one rollout (clock-masked hash), its action, and the cache run's outcome."""
import glob, hashlib, json, re, sys
sys.path[:0] = ["/mnt/ssd2/vikranth/osworld"]
from toolspec.keys import action_key
T = "/mnt/ssd2/vikranth/osworld/traces"
CLOCK = re.compile(r"\b\d{1,2}:\d{2}( [AP]M)?\b")
rec = glob.glob(f"{T}/rec128e2_shot/*/7a4e4bc8*__g4")[0]
sc = glob.glob(f"{T}/r128e2_SC2/*/7a4e4bc8*__g4")[0]
ch = [json.loads(l) for l in open(f"{rec}/chat.jsonl")]
tr = [json.loads(l) for l in open(f"{sc}/traj.jsonl")]
chk = {e["step"]: e["ok"] for e in map(json.loads, open(f"{T}/r128e2_SC2/events.jsonl"))
       if e["event"] == "scache_check" and e["task"].startswith("7a4e4bc8") and e["k"] == 4}
names, seen = {}, {}
for i, c in enumerate(ch[:len(tr)]):
    m = c["messages"][-1]["content"]
    text = (m[-1]["text"] if isinstance(m, list) else m).split("Accessibility tree:\n", 1)[1].rsplit("\n\nNext action?", 1)[0]
    h = hashlib.sha1(CLOCK.sub("", text).encode()).hexdigest()
    names.setdefault(h, "S%d" % len(names))
    key = action_key(json.loads(tr[i]["action"]), tr[i].get("a11y_hit"))
    pair = (names[h], key)
    src = "" if tr[i].get("skipped") != "scache" else f"from step {seen[pair]}" if pair in seen else "from earlier traces/siblings"
    print(f"step {i + 1:2d}: screen {names[h]:4s} action {str(key)[:45]:45s} {'HIT ' if tr[i].get('skipped') == 'scache' else 'miss'} {src:28s}"
          f"{'' if i + 1 not in chk else 'check ok' if chk[i + 1] else 'check REJECTED'}")
    seen.setdefault(pair, i + 1)
