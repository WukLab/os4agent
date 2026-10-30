"""Offline: speculate from the model's thinking as it streams. For each step the screen cache missed, find how far
into the thinking the final action's target (element name, or the text it types) is first named; if the tokens stream
at a steady rate, a copy could start that action at that point instead of after the model finishes.

  python3 think_stream_sim.py SC_RUN RECORDING [MIN_FRAC]

Saving for a miss whose target appears at fraction f of the thinking (t = model time, e = env time of the step):
min(e, (1 - f) * t) -- the copy runs the action during the rest of the thinking. Only the first mention counts, and a
mention is only usable if no *other* element is named after it (else the target is ambiguous): we report both.
"""
import glob, json, os, re, sys

sc, rec = sys.argv[1], sys.argv[2]
ev = [json.loads(l) for l in open(f"{sc}/events.jsonl")]
t0 = ev[0]["t"]
end = {(e["task"], e["k"]): e["t"] - t0 for e in ev if e["event"] == "rollout_done"}


def target(act, hit):
    """Strings that identify the action in prose: the element's name (cells: the cell ref and its value), typed text."""
    out = []
    if hit and hit.get("name"):
        n = hit["name"]
        m = re.match(r"^([A-Z]{1,3}\d+): ?(.*)$", n)  # Calc cells are named "E1: Date"
        out += [m.group(1)] + ([m.group(2)] if m and len(m.group(2)) > 2 else []) if m else [n]
    if act.get("text") and len(act["text"].strip()) > 2:
        out.append(act["text"].strip())
    if act.get("action") in ("hotkey", "key", "press") and act.get("keys"):
        out.append(str(act["keys"]))
    return [x for x in out if len(x) >= 2]


found = total = 0
fracs, saved = [], {}
per_rollout = {}
for d in glob.glob(f"{sc}/*/*__g*"):
    task, k = os.path.basename(d).split("__g")
    k = int(k)
    tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")]
    ch = [json.loads(l) for l in open(d.replace(sc, rec) + "/chat.jsonl")]
    sv, rows = 0.0, []
    for i, s in enumerate(tr):
        if s.get("skipped") == "scache" or i >= len(ch):
            continue
        act = json.loads(s["action"])
        if act.get("action") in ("done", "fail", "invalid"):
            continue
        resp = ch[i].get("response") or ""
        think = resp.split("</think>")[0] if "</think>" in resp else resp.rsplit("Action:", 1)[0]
        if not think:
            continue
        total += 1
        names = target(act, s.get("a11y_hit"))
        low = think.lower()
        pos = [low.find(x.lower()) for x in names if low.find(x.lower()) >= 0]
        t = (ch[i].get("t") or {})
        t = t.get("llm_end", 0) - t.get("llm_start", 0)
        if pos:
            f = min(pos) / max(1, len(think))
            found += 1
            fracs.append(f)
            g = min(s["exec_s"], (1 - f) * t)
            sv += g
            rows.append((i + 1, round(f, 2), round(g)))
    saved[(task, k)] = sv
    per_rollout[(task, k)] = rows

fracs.sort()
q = lambda p: fracs[int(len(fracs) * p)] if fracs else float("nan")
print(f"cache misses with thinking: {total}; target named in the thinking: {found} ({found / max(1, total):.0%})")
print(f"where it is first named (fraction of the thinking): p25 {q(.25):.2f}, median {q(.5):.2f}, p75 {q(.75):.2f}")
base = sorted(end.values())
new = sorted(end[r] - saved.get(r, 0) for r in end)
print(f"upper bound (every first mention used, right): epoch {base[-1] / 60:.2f} -> {new[-1] / 60:.2f} min "
      f"({new[-1] / base[-1] - 1:+.1%} vs cache alone); 99% {base[int(len(base) * .99) - 1] / 60:.2f} -> {new[int(len(new) * .99) - 1] / 60:.2f}")
last = max(end, key=end.get)
print("slowest rollout", last[0][:8], last[1], "misses (step, fraction, s saved):", per_rollout[last])
