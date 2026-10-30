"""GUI agent for OSWorld: the model sees the accessibility tree (A11Y_SCREENSHOT=1: plus the screenshot) and picks
elements by id.

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
CHECKABLE = {"check-box", "toggle-button", "radio-button", "check-menu-item", "radio-menu-item"}
MAX_ROWS = int(os.environ.get("A11Y_MAX_ROWS", "400"))
HISTORY = int(os.environ.get("A11Y_HISTORY", "5"))
SYSTEM = """You are a GUI agent controlling an Ubuntu desktop. You cannot see the screen; you get its accessibility tree as rows `[id] role "name"`.
Pick the element to act on by its numeric id. Reply with a one-sentence Thought, then ONE line that starts with `Action:` followed by a JSON object. Example reply:
Thought: I need to open the Chrome menu to reach settings.
Action: {"action": "click", "id": 12}
Available actions (JSON):
{"action": "click", "id": N}   {"action": "double_click", "id": N}   {"action": "right_click", "id": N}
{"action": "type", "text": "hello"}  (to press Enter after typing, end the JSON string with one \\n: "hello\\n")   {"action": "key", "keys": ["ctrl", "s"]}
{"action": "scroll", "id": N, "direction": "down"}   {"action": "drag", "from": N, "to": M}   {"action": "wait"}
{"action": "done"} when the task is complete   {"action": "fail"} only if it is impossible.
Always use the numeric id, never the element name. Element ids are renumbered every step: use only ids from the
current tree, never ids from previous actions. If what you need is not in the tree, never guess an id: use a keyboard
shortcut (e.g. ctrl+b for bold, space to play) or open a menu that is in the tree."""
REASON = os.environ.get("A11Y_REASON", "0") == "1"  # 1: free-length Thought instead of one sentence (max_tokens 300 -> 1024)
if REASON:
    SYSTEM = SYSTEM.replace("Reply with a one-sentence Thought, then ONE line",
                            "Think step by step in a Thought as long as you need, then end with ONE line")
# Thinking models (<think>...</think>): at most this many tokens of thinking; past it the thinking is closed for the model
# and it must answer (Qwen3-VL-Thinking can loop on Calc without ever closing it). 0 = no budget.
THINK_BUDGET = int(os.environ.get("A11Y_THINK_BUDGET", "0"))
THINK_CLOSE = "\n\nI have thought enough; I'll answer now.\n</think>\n\nThought:"
# A11Y_SCREENSHOT=1: the user message also carries the screenshot (JPEG, longest side A11Y_SHOT_PX), next to the tree.
# Actions stay tree ids. vLLM must allow one image per prompt (vllm_ctl.sh IMAGES=1).
SHOT = os.environ.get("A11Y_SCREENSHOT", "0") == "1"
SHOT_PX = int(os.environ.get("A11Y_SHOT_PX", "1280"))
if SHOT:
    SYSTEM = SYSTEM.replace(
        "You cannot see the screen; you get its accessibility tree as rows `[id] role \"name\"`.\nPick the element to act on by its numeric id.",
        "You get a screenshot of the screen and its accessibility tree as rows `[id] role \"name\"`. Use the screenshot to "
        "see the state of the screen (contents, values, what changed); act on elements of the tree.\nPick the element to "
        "act on by its numeric id from the tree.")
    assert "You get a screenshot" in SYSTEM
# A11Y_STOP_DONE=1: tell the model to stop once the goal is visibly met (solved rollouts otherwise keep re-checking,
# fiddling or undoing until the step cap)
if os.environ.get("A11Y_STOP_DONE", "0") == "1":
    SYSTEM = SYSTEM.replace('{"action": "done"} when the task is complete',
                            '{"action": "done"} as soon as the screen shows the task is complete: do not re-check, '
                            'redo or undo finished work')
    assert "as soon as the screen shows" in SYSTEM


def shot_url(png):
    """Screenshot PNG bytes -> data URL of a downscaled JPEG."""
    import base64, io
    from PIL import Image
    im = Image.open(io.BytesIO(png)).convert("RGB")
    im.thumbnail((SHOT_PX, SHOT_PX))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


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
    active = next(w for w in wins if _box(w) == top)
    # an active window with nothing of its own in the tree (e.g. VLC's video surface) must not hide the window under it
    if sum(1 for e in active.iter() if e is not active and _box(e) and (e.get("name") or "").strip()) < 3:
        return set()
    # a window much smaller than the active one and inside it is a dialog/popup in front of it (LibreOffice keeps its
    # main window active under a non-modal dialog), not a background window behind it: only big windows are hidden
    big = lambda w: _box(w)[2] * _box(w)[3] >= 0.5 * tw * th
    return {e for w in wins if w.tag in ("frame", "dialog") and _attr(w, "active") != "true" and big(w) for e in w.iter()
            if (b := _box(e)) and tx <= b[0] and ty <= b[1] and b[0] + b[2] <= tx + tw and b[1] + b[3] <= ty + th}


def closed_dropdown_items(root):
    """Entries of combo-box lists that are not expanded: LibreOffice reports a closed font/style/name list's entries as
    showing and visible (on top of the sheet), filling the row limit with things that are not on screen."""
    out = set()
    for cb in root.iter():
        if cb.tag == "combo-box" and _attr(cb, "expanded") != "true":
            out |= {e for e in cb.iter() if e.tag in ("list", "list-item", "menu-item")}
    return out


def extra_menubars(root):
    """LibreOffice on GTK3 exposes its menus twice: the real GTK menu bar and an internal copy reported ~27px lower, on
    the toolbar (a click on its "Format" hits Print). Per window keep only the topmost menu bar."""
    out = set()
    top = lambda b: min((bx[1] for m in b if (bx := _box(m))), default=None)  # the bar itself has no box; its menus do
    for win in root.iter():
        if win.tag not in ("frame", "window"):
            continue
        bars = sorted((b for b in win.iter() if b.tag == "menu-bar" and top(b) is not None), key=top)
        out |= {e for b in bars[1:] for e in b.iter()}
    return out


LABELLED = {"text", "entry", "combo-box", "spin-button", "tree-table", "table", "list", "tree", "password-text"}


def label_for(b, labels):
    """Name for an unnamed, empty control from the label beside it: on its row just to the left (Writer's "Size:" field)
    or just above it (Calc pivot layout's "Row Fields:" drop list). AT-SPI's labelled-by relation is not in the XML."""
    x, y, w, h = b
    left = [(x - lx - lw, t) for t, (lx, ly, lw, lh) in labels if abs((ly + lh / 2) - (y + h / 2)) <= 12 and -10 <= x - lx - lw <= 150]
    above = [(y - ly - lh, t) for t, (lx, ly, lw, lh) in labels if -5 <= y - ly - lh <= 25 and lx < x + w and x < lx + lw]
    best = min(left + above, default=None)  # the closest label wins
    return best[1].rstrip(":").strip() if best else ""


def far_empty_cells(root):
    """Empty Calc cells more than one row/column past the last non-empty one: the server lists every visible cell
    (~1000), which would fill the row limit. The next free row and column stay, for new headers and results."""
    cells = [(e, m) for e in root.iter() if e.tag == "table-cell" and (m := re.fullmatch(r"([A-Z]+)(\d+)", e.get("name") or ""))]
    col = lambda s: sum((ord(c) - 64) * 26 ** i for i, c in enumerate(reversed(s)))
    full = [(col(m[1]), int(m[2])) for e, m in cells if (e.text or "").strip()]
    mc, mr = max((c for c, _ in full), default=1) + 1, max((r for _, r in full), default=1) + 1
    return {e for e, m in cells if not (e.text or "").strip() and (col(m[1]) > mc or int(m[2]) > mr)}


def linearize(tree_xml):
    """-> (prompt text, rows) with rows[id] = (role, name, (x, y, w, h)). Over MAX_ROWS, non-interactive rows go first."""
    root = ET.fromstring(tree_xml)
    hidden = occluded(root) | closed_dropdown_items(root)
    hidden |= far_empty_cells(root) | extra_menubars(root)
    labels = [(n, lb) for e in root.iter() if e.tag == "label" and (lb := _box(e))
              and (n := (e.get("name") or "").strip() or (e.text or "").strip())]
    rows = []
    for e in root.iter():
        # no name -> the element's text (LibreOffice paragraphs and labels carry their text there, with an empty name)
        b, name = _box(e), ((e.get("name") or "").strip() or (e.text or "").strip())
        if b and not name and e.tag in LABELLED and "true" in (_attr(e, "focusable"), _attr(e, "editable")):
            name = label_for(b, labels)  # unnamed empty field / list: name it after its label so it can be targeted
        if e.tag == "table-cell" and (e.text or "").strip() and name != e.text.strip():
            name = f"{name}: {e.text.strip()}"  # Calc cells: name is the address (A2), the value is the text
        if b and name and e not in hidden:
            # on/off state of checkable controls, shown but not part of the row (refind matches role + name across steps)
            on = e.tag in CHECKABLE and ("true" in (_attr(e, "checked"), _attr(e, "pressed")))
            state = (" [on]" if on else " [off]") if e.tag in CHECKABLE else ""
            if e.tag == "page-tab" and _attr(e, "selected") == "true":
                state = " [selected]"  # which sheet / dialog page / browser tab is active (Calc's sheets can look identical)
            rows.append((e.tag, name[:80], b, state))
    if len(rows) > MAX_ROWS:
        keep = [i for i, r in enumerate(rows) if r[0] in INTERACTIVE]
        rest = [i for i, r in enumerate(rows) if r[0] not in INTERACTIVE]
        rows = [rows[i] for i in sorted((keep + rest)[:MAX_ROWS])]
    return "\n".join(f'[{i}] {r} "{n}"{s}' for i, (r, n, _, s) in enumerate(rows)), [r[:3] for r in rows]


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
        while text.endswith("\\n"):  # a literal backslash-n (escaped twice in the model's JSON) also means Enter
            text = text[:-2] + "\n"
        enter = text.endswith("\n")
        text = text.rstrip("\n").replace("\\", "\\\\").replace("'", "\\'")
        return f"import pyautogui\npyautogui.write('{text}', interval=0.02)" + ("\npyautogui.press('enter')" if enter else "")
    if kind == "key":
        return "import pyautogui\npyautogui.hotkey(" + ", ".join(repr(str(k)) for k in act["keys"]) + ")"
    if kind == "scroll":
        x, y = center(act["id"])
        return f"import pyautogui\npyautogui.scroll({-5 if act.get('direction', 'down') == 'down' else 5}, x={x}, y={y})"
    if kind == "drag":
        if act["from"] == act["to"]:
            # a drag onto the element it starts on moves nothing; performed, LibreOffice (GTK3) starts a drag-and-drop
            # and blocks ~2 min (and the tree with it) before cancelling the drop on its origin: do nothing instead
            return "WAIT"
        (x1, y1), (x2, y2) = center(act["from"]), center(act["to"])
        # GTK3 drag-and-drop (e.g. Calc's pivot-table layout fields) ignores a fast or tweened dragTo; what works (tested on
        # the pivot dialog): press, pause, move past the drag threshold, 20 paced steps, hover with a small wiggle, release
        return (f"import pyautogui, time\npyautogui.PAUSE = 0\npyautogui.moveTo({x1}, {y1}); time.sleep(0.2)\n"
                f"pyautogui.mouseDown(); time.sleep(0.3)\npyautogui.moveTo({x1 + 12}, {y1 + 6}); time.sleep(0.3)\n"
                f"for i in range(1, 21):\n    pyautogui.moveTo({x1} + ({x2} - {x1}) * i // 20, {y1} + ({y2} - {y1}) * i // 20); time.sleep(0.05)\n"
                f"time.sleep(0.4); pyautogui.moveTo({x2 + 3}, {y2 + 2}); time.sleep(0.3); pyautogui.moveTo({x2}, {y2}); time.sleep(0.3)\n"
                f"pyautogui.mouseUp()")
    if kind in ("wait", "done", "fail"):
        return kind.upper()
    raise ValueError(f"unknown action {kind}")


def parse(response):
    """The first (A11Y_REASON=1: last) `Action: {json}` in the response; ids may come as N, [N] or "N"."""
    i = response.rfind("Action:") if REASON else response.find("Action:")  # a long Thought may say "Action:" too
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
    def __init__(self, model, temperature=1.0, top_p=0.9, max_tokens=1024 if REASON else 300):
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
        user = f"Task: {instruction}\n\nPrevious actions:\n{hist}\n\nAccessibility tree:\n{text}\n\nNext action?"
        logged = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
        msgs = logged
        if SHOT and obs.get("screenshot"):  # the image goes to the model; chat.jsonl keeps a placeholder (step_N.png has it)
            # task + history first (the same text step after step, so it stays in vLLM's prefix cache), then the image
            head = f"Task: {instruction}\n\nPrevious actions:\n{hist}\n\nScreenshot of the screen:"
            tail = f"Accessibility tree:\n{text}\n\nNext action?"
            msgs = [logged[0], {"role": "user", "content": [
                {"type": "text", "text": head}, {"type": "image_url", "image_url": {"url": shot_url(obs["screenshot"])}},
                {"type": "text", "text": tail}]}]
            logged = [logged[0], {"role": "user", "content": [
                {"type": "text", "text": head}, {"type": "image", "image": "<screenshot>"}, {"type": "text", "text": tail}]}]
        t_llm = time.time()
        r = self.client.chat.completions.create(model=self.model, messages=msgs, temperature=self.temperature,
                                                top_p=self.top_p, max_tokens=THINK_BUDGET or self.max_tokens)
        resp, out_tokens = r.choices[0].message.content or "", r.usage.completion_tokens
        if THINK_BUDGET and "</think>" not in resp:  # over budget: close the thinking, continue the same message
            resp += THINK_CLOSE
            r2 = self.client.chat.completions.create(
                model=self.model, messages=msgs + [{"role": "assistant", "content": resp}], temperature=self.temperature,
                top_p=self.top_p, max_tokens=300, extra_body={"add_generation_prompt": False, "continue_final_message": True})
            resp += r2.choices[0].message.content or ""
            out_tokens += r2.usage.completion_tokens
        if THINK_BUDGET and "</think>" in resp:  # the answer itself ran out of tokens: let it finish (once)
            try:
                parse(resp.rsplit("</think>", 1)[-1])
            except Exception:
                r3 = self.client.chat.completions.create(
                    model=self.model, messages=msgs + [{"role": "assistant", "content": resp}], temperature=self.temperature,
                    top_p=self.top_p, max_tokens=200, extra_body={"add_generation_prompt": False, "continue_final_message": True})
                resp += r3.choices[0].message.content or ""
                out_tokens += r3.usage.completion_tokens
        t_llm_end = time.time()
        try:
            act = parse(resp.rsplit("</think>", 1)[-1])  # the answer, not an Action: written while thinking
            code = to_code(act, rows)
        except Exception as e:  # invalid output is a logged no-op
            act, code = {"action": "invalid", "error": repr(e)}, "WAIT"
        i = act.get("id", act.get("from"))
        target = f'  [{rows[i][0]} "{rows[i][1]}"]' if isinstance(i, int) and 0 <= i < len(rows) else ""
        # no ids in the history: ids are renumbered every step, and a stale id points at another element
        self.hist.append(json.dumps({k: v for k, v in act.items() if k not in ("id", "from", "to")}) + target)
        self.last = {"messages": logged, "response": resp, "action": act, "code": code,
                     "rows": [[role, name, list(b)] for role, name, b in rows],
                     "prompt_tokens": r.usage.prompt_tokens, "completion_tokens": out_tokens,
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
