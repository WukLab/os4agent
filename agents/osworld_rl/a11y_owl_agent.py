"""Text-only GUI agent for OSWorld: the model sees the accessibility tree (no pixels) and picks elements by id.

Observation rows:  [id] role "name"
Actions (one JSON object after "Action:"):
  click / double_click / right_click {"id": N}    type {"text": "..."} (trailing \\n presses Enter)
  key {"keys": ["ctrl", "s"]}    scroll {"id": N, "direction": "up|down"}    drag {"from": N, "to": M}
  wait | done | fail
Every step (messages, response, action, id -> element table) is appended to chat.jsonl, which osw_run.py replays
and train_grpo.py trains on.
"""
import json, os, re, time, xml.etree.ElementTree as ET
from openai import OpenAI

INTERACTIVE = {"push-button", "toggle-button", "menu-item", "check-menu-item", "radio-menu-item", "check-box", "radio-button",
               "link", "entry", "password-text", "combo-box", "page-tab", "list-item", "tree-item", "table-cell", "menu", "icon",
               "spin-button", "slider", "text", "paragraph", "terminal", "table-row", "column-header", "tool-bar-button"}
MAX_ROWS = int(os.environ.get("A11Y_MAX_ROWS", "400"))
HISTORY = int(os.environ.get("A11Y_HISTORY", "5"))
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


# ---------------------------------------------------------------- accessibility tree

def _attr(e, name):
    """Attributes are namespaced ({ns}showing); match the local name exactly."""
    return next((v for k, v in e.attrib.items() if k.rsplit("}", 1)[-1] == name), None)


def _box(e):
    """-> (x, y, w, h) of a showing element, else None."""
    sc, sz = _attr(e, "screencoord"), _attr(e, "size")
    if not sc or not sz or _attr(e, "showing") == "false":
        return None
    xy, wh = re.findall(r"-?\d+", sc), re.findall(r"-?\d+", sz)
    if len(xy) < 2 or len(wh) < 2:
        return None
    x, y, w, h = int(xy[0]), int(xy[1]), int(wh[0]), int(wh[1])
    return (x, y, w, h) if w > 0 and h > 0 else None


def occluded(root):
    """Elements of background frames/dialogs that lie under the active window.
    AT-SPI marks every non-minimised window as showing, so two maximised windows would both appear in full."""
    wins = [w for app in root if app.get("name") != "gnome-shell" for w in app if _box(w)]
    top = next((_box(w) for w in wins if _attr(w, "active") == "true" and _attr(w, "window-type") != "desktop"), None)
    if not top:
        return set()
    tx, ty, tw, th = top
    return {e for w in wins if w.tag in ("frame", "dialog") and _attr(w, "active") != "true" for e in w.iter()
            if (b := _box(e)) and tx <= b[0] and ty <= b[1] and b[0] + b[2] <= tx + tw and b[1] + b[3] <= ty + th}


def linearize(tree_xml):
    """-> (prompt text, rows) with rows[id] = (role, name, (x, y, w, h)). Over MAX_ROWS, non-interactive rows go first."""
    root = ET.fromstring(tree_xml)
    hidden = occluded(root)
    rows = []
    for e in root.iter():
        b, name = _box(e), (e.get("name") or "").strip()
        if b and name and e not in hidden:
            rows.append((e.tag, name[:80], b))
    if len(rows) > MAX_ROWS:
        keep = [i for i, r in enumerate(rows) if r[0] in INTERACTIVE]
        rest = [i for i, r in enumerate(rows) if r[0] not in INTERACTIVE]
        rows = [rows[i] for i in sorted((keep + rest)[:MAX_ROWS])]
    return "\n".join(f'[{i}] {r} "{n}"' for i, (r, n, _) in enumerate(rows)), rows


def refind(row, rows):
    """Id of the element in rows with row's role and name, nearest to its old position; None if there is none."""
    role, name, (x, y, w, h) = row
    hits = [j for j, r in enumerate(rows) if r[0] == role and r[1] == name]
    dist = lambda j: abs(rows[j][2][0] + rows[j][2][2] / 2 - x - w / 2) + abs(rows[j][2][1] + rows[j][2][3] / 2 - y - h / 2)
    return min(hits, key=dist) if hits else None


# ---------------------------------------------------------------- actions

ALIASES = {"terminate": "done", "finish": "done", "finished": "done", "complete": "done", "success": "done"}
CLICKS = {"click": "click", "double_click": "doubleClick", "right_click": "rightClick"}


def to_code(act, rows):
    """Action dict -> pyautogui code (or DONE / FAIL / WAIT). Raises on a bad id."""
    kind = ALIASES.get(act.get("action"), act.get("action"))

    def center(i):
        x, y, w, h = rows[int(i)][2]
        return x + w // 2, y + h // 2

    if kind in CLICKS:
        x, y = center(act["id"])
        return f"import pyautogui\npyautogui.{CLICKS[kind]}({x}, {y})"
    if kind == "type":
        text = str(act["text"])
        enter = text.endswith("\n")
        text = text.rstrip("\n").replace("\\", "\\\\").replace("'", "\\'")
        return f"import pyautogui\npyautogui.write('{text}', interval=0.02)" + ("\npyautogui.press('enter')" if enter else "")
    if kind == "key":
        return "import pyautogui\npyautogui.hotkey(" + ", ".join(repr(str(k)) for k in act["keys"]) + ")"
    if kind == "scroll":
        x, y = center(act["id"])
        return f"import pyautogui\npyautogui.scroll({-5 if act.get('direction', 'down') == 'down' else 5}, x={x}, y={y})"
    if kind == "drag":
        (x1, y1), (x2, y2) = center(act["from"]), center(act["to"])
        return f"import pyautogui\npyautogui.moveTo({x1}, {y1})\npyautogui.dragTo({x2}, {y2}, duration=0.5)"
    if kind in ("wait", "done", "fail"):
        return kind.upper()
    raise ValueError(f"unknown action {kind}")


def parse(response):
    """The first `Action: {json}` in the response; ids may come as N, [N] or "N"."""
    i = response.find("Action:")
    j = response.find("{", i) if i >= 0 else -1
    act = None
    if j >= 0:
        try:
            act, _ = json.JSONDecoder().raw_decode(response[j:])
        except json.JSONDecodeError:
            pass
    if act is None and i >= 0:  # plain-text fallback: "Action: click id: 15" / "click(15)"
        if m := re.match(r"Action:\s*(click|double_click|right_click)\W+(?:id\W*)?(\d+)", response[i:]):
            act = {"action": m.group(1), "id": int(m.group(2))}
    if act is None:
        raise ValueError("no parsable Action")
    for k in ("id", "from", "to"):
        if k in act:
            v = act[k]
            if isinstance(v, list) and v:
                v = v[0]
            if isinstance(v, str) and v.strip().isdigit():
                v = int(v)
            act[k] = v
    return act


# ---------------------------------------------------------------- agent

class A11yAgent:
    def __init__(self, model, temperature=1.0, top_p=0.9, max_tokens=300):
        self.model, self.temperature, self.top_p, self.max_tokens = model, temperature, top_p, max_tokens
        self.client = OpenAI(base_url=os.environ["DOUBAO_API_URL"], api_key=os.environ.get("DOUBAO_API_KEY", "x"))
        self.log = None   # chat.jsonl path, set by the runner
        self.last = None  # the latest step record (what chat.jsonl gets)
        self.reset()

    def reset(self):
        self.hist, self.t_reset = [], time.time()

    def predict(self, instruction, obs):
        t_obs = time.time()
        text, rows = linearize(obs["accessibility_tree"])
        hist = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(self.hist[-HISTORY:])) or "(none)"
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Task: {instruction}\n\nPrevious actions:\n{hist}\n\nAccessibility tree:\n{text}\n\nNext action?"}]
        t_llm = time.time()
        r = self.client.chat.completions.create(model=self.model, messages=msgs, temperature=self.temperature,
                                                top_p=self.top_p, max_tokens=self.max_tokens)
        t_llm_end = time.time()
        resp = r.choices[0].message.content or ""
        try:
            act = parse(resp)
            code = to_code(act, rows)
        except Exception as e:  # invalid output is a logged no-op
            act, code = {"action": "invalid", "error": repr(e)}, "WAIT"
        i = act.get("id", act.get("from"))
        target = f'  [{rows[i][0]} "{rows[i][1]}"]' if isinstance(i, int) and 0 <= i < len(rows) else ""
        self.hist.append(json.dumps(act) + target)
        self.last = {"messages": msgs, "response": resp, "action": act, "code": code,
                     "rows": [[role, name, list(b)] for role, name, b in rows],
                     "prompt_tokens": r.usage.prompt_tokens, "completion_tokens": r.usage.completion_tokens,
                     "t": {"reset": self.t_reset, "obs": t_obs, "llm_start": t_llm, "llm_end": t_llm_end}}
        if self.log:
            with open(self.log, "a") as f:
                f.write(json.dumps(self.last) + "\n")
        return resp, [code]


if __name__ == "__main__":  # self-check: python a11y_owl_agent.py
    xml = ('<desktop xmlns:c="urn:c" xmlns:s="urn:s"><application name="app">'
           '<frame name="Win" c:screencoord="(0, 0)" c:size="(100, 100)" s:active="true">'
           '<push-button name="OK" c:screencoord="(10, 20)" c:size="(30, 10)"/>'
           '<label name="" c:screencoord="(0, 0)" c:size="(5, 5)"/></frame></application></desktop>')
    _, rows = linearize(xml)
    assert rows == [("frame", "Win", (0, 0, 100, 100)), ("push-button", "OK", (10, 20, 30, 10))], rows
    assert to_code(parse('Thought: x\nAction: {"action": "click", "id": "1"}'), rows) == "import pyautogui\npyautogui.click(25, 25)"
    assert parse("Action: click id: 1") == {"action": "click", "id": 1}
    assert to_code({"action": "finish"}, rows) == "DONE"
    moved = [("push-button", "OK", (500, 500, 30, 10)), ("frame", "Win", (0, 0, 100, 100)), ("push-button", "OK", (12, 20, 30, 10))]
    assert refind(rows[1], moved) == 2 and refind(("link", "x", (0, 0, 1, 1)), moved) is None
    print("ok")
