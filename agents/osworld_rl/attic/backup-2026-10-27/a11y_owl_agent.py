"""Text-only (accessibility-tree) GUI agent for OSWorld. Model sees NO pixels; it picks elements by id.
Used by osw_run.py (replayed by its ReplayAgent).
Observation rows:  [id] role "name"        (showing, named elements; interactive roles first if the list must be cut)
Action (one JSON object after 'Action:'):
  {"action":"click","id":N} | {"action":"double_click","id":N} | {"action":"right_click","id":N}
  {"action":"type","text":"..."}   (append \\n to press Enter)   | {"action":"key","keys":["ctrl","s"]}
  {"action":"scroll","id":N,"direction":"up|down"} | {"action":"drag","from":N,"to":M} | {"action":"wait"} | {"action":"done"} | {"action":"fail"}
Every step's (messages, response, id->element table) is appended to <result_dir>/chat.jsonl for replay and GRPO training."""
import json, os, re, time, xml.etree.ElementTree as ET
from openai import OpenAI
from a11y_hit import _box, occluded   # lives in the OSWorld root (copied by setup)

INTERACTIVE = {"push-button", "toggle-button", "menu-item", "check-menu-item", "radio-menu-item", "check-box", "radio-button", "link", "entry",
               "password-text", "combo-box", "page-tab", "list-item", "tree-item", "table-cell", "menu", "icon", "spin-button", "slider", "text",
               "paragraph", "terminal", "table-row", "column-header", "tool-bar-button"}
MAX_ROWS, HISTORY = int(os.environ.get("A11Y_MAX_ROWS", "400")), int(os.environ.get("A11Y_HISTORY", "5"))
SYSTEM = """You are a GUI agent controlling an Ubuntu desktop. You cannot see the screen; you get its accessibility tree as rows `[id] role "name"`.
Pick the element to act on by its numeric id. Reply with a one-sentence Thought, then ONE line that starts with `Action:` followed by a JSON object. Example reply:
Thought: I need to open the Chrome menu to reach settings.
Action: {"action": "click", "id": 12}
Available actions (JSON):
{"action": "click", "id": N}   {"action": "double_click", "id": N}   {"action": "right_click", "id": N}
{"action": "type", "text": "hello"}  (end the text with \\n to press Enter)   {"action": "key", "keys": ["ctrl", "s"]}
{"action": "scroll", "id": N, "direction": "down"}   {"action": "drag", "from": N, "to": M}   {"action": "wait"}
{"action": "done"} when the task is complete   {"action": "fail"} only if it is impossible.
Always use the numeric id, never the element name."""


def linearize(tree_xml):
    """-> (text, rows) ; rows[i] = (role, name, (x,y,w,h)) for id i. Background windows hidden under the active one are dropped."""
    rows = []; root = ET.fromstring(tree_xml); hidden = occluded(root)
    for e in root.iter():
        b, nm = _box(e), (e.get("name") or "").strip()
        if b and nm and e not in hidden: rows.append((e.tag, nm[:80], b))
    if len(rows) > MAX_ROWS:  # drop non-interactive rows first, keep document order
        keep = {i for i, r in enumerate(rows) if r[0] in INTERACTIVE}
        extra = [i for i in range(len(rows)) if i not in keep]
        idx = sorted(list(keep)[:MAX_ROWS] if len(keep) >= MAX_ROWS else list(keep) + extra[:MAX_ROWS - len(keep)])
        rows = [rows[i] for i in idx]
    return "\n".join(f'[{i}] {r} "{n}"' for i, (r, n, _) in enumerate(rows)), rows


def to_code(act, rows):
    """action dict -> pyautogui code string (or DONE/FAIL/WAIT). Raises ValueError on a bad id."""
    a = {"terminate": "done", "finish": "done", "finished": "done", "complete": "done", "success": "done"}.get(act.get("action"), act.get("action"))
    ctr = lambda i: (rows[i][2][0] + rows[i][2][2] // 2, rows[i][2][1] + rows[i][2][3] // 2)
    if a in ("click", "double_click", "right_click"):
        x, y = ctr(int(act["id"])); fn = {"click": "click", "double_click": "doubleClick", "right_click": "rightClick"}[a]
        return f"import pyautogui\npyautogui.{fn}({x}, {y})"
    if a == "type":
        t = str(act["text"]); enter = t.endswith("\n"); t = t.rstrip("\n").replace("\\", "\\\\").replace("'", "\\'")
        return f"import pyautogui\npyautogui.write('{t}', interval=0.02)" + ("\npyautogui.press('enter')" if enter else "")
    if a == "key": return "import pyautogui\npyautogui.hotkey(" + ", ".join(repr(str(k)) for k in act["keys"]) + ")"
    if a == "scroll":
        x, y = ctr(int(act["id"])); return f"import pyautogui\npyautogui.scroll({-5 if act.get('direction', 'down') == 'down' else 5}, x={x}, y={y})"
    if a == "drag":
        (x1, y1), (x2, y2) = ctr(int(act["from"])), ctr(int(act["to"])); return f"import pyautogui\npyautogui.moveTo({x1}, {y1})\npyautogui.dragTo({x2}, {y2}, duration=0.5)"
    if a in ("wait",): return "WAIT"
    if a == "done": return "DONE"
    if a == "fail": return "FAIL"
    raise ValueError(f"unknown action {a}")


def parse(response):
    """First 'Action: {json}' only (the model sometimes emits several); ids may come as N, [N] or "N"."""
    i = response.find("Action:")
    j = response.find("{", i) if i >= 0 else -1
    act = None
    if j >= 0:
        try: act, _ = json.JSONDecoder().raw_decode(response[j:])
        except json.JSONDecodeError: act = None
    if act is None and i >= 0:  # plain-text fallback: "Action: click id: 15" / "click(15)"
        m = re.match(r"Action:\s*(click|double_click|right_click)\W+(?:id\W*)?(\d+)", response[i:])
        if m: act = {"action": m.group(1), "id": int(m.group(2))}
    if act is None: raise ValueError("no parsable Action")
    for k in ("id", "from", "to"):
        v = act.get(k)
        if isinstance(v, list) and v: v = v[0]
        if isinstance(v, str) and v.strip().isdigit(): v = int(v)
        if k in act: act[k] = v
    return act


class A11yAgent:
    def __init__(self, model, temperature=1.0, top_p=0.9, max_tokens=300, **_):
        self.model, self.t, self.p, self.mt = model, temperature, top_p, max_tokens
        self.client = OpenAI(base_url=os.environ["DOUBAO_API_URL"], api_key=os.environ.get("DOUBAO_API_KEY", "x"))
        self.reset()

    def reset(self, runtime_logger=None, **_):
        self.hist, self.log, self.t_reset = [], None, time.time()   # called right after env.reset (VM setup done)
        for h in getattr(runtime_logger, "handlers", []):  # result dir = where the runner writes runtime.log
            if hasattr(h, "baseFilename"): self.log = os.path.join(os.path.dirname(h.baseFilename), "chat.jsonl")

    def predict(self, instruction, obs):
        t_obs = time.time()   # previous action executed + new observation fetched
        text, rows = linearize(obs["accessibility_tree"])
        hist = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(self.hist[-HISTORY:])) or "(none)"
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Task: {instruction}\n\nPrevious actions:\n{hist}\n\nAccessibility tree:\n{text}\n\nNext action?"}]
        t_llm = time.time()   # x-task tags this request in the proxy's llm.jsonl with the rollout dir
        r = self.client.chat.completions.create(model=self.model, messages=msgs, temperature=self.t, top_p=self.p, max_tokens=self.mt,
                                                extra_headers={"x-task": os.path.dirname(self.log or "")})
        t_llm_end = time.time(); resp = r.choices[0].message.content or ""
        try: act = parse(resp); code = to_code(act, rows)
        except Exception as e: act, code = {"action": "invalid", "error": repr(e)}, "WAIT"   # invalid output = no-op, logged
        d = act.get("id", act.get("from"))
        self.hist.append(json.dumps(act) + (f'  [{rows[int(d)][0]} "{rows[int(d)][1]}"]' if isinstance(d, int) and 0 <= d < len(rows) else ""))
        if self.log:
            with open(self.log, "a") as f:
                f.write(json.dumps({"messages": msgs, "response": resp, "action": act, "code": code, "rows": [[a, b, list(c)] for a, b, c in rows],
                                    "prompt_tokens": r.usage.prompt_tokens, "completion_tokens": r.usage.completion_tokens,
                                    "t": {"reset": self.t_reset, "obs": t_obs, "llm_start": t_llm, "llm_end": t_llm_end}}) + "\n")
        return resp, [code]
