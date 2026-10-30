"""Text-only (accessibility-style) web agent for WebArena shopping. Same shape as osworld_rl/a11y_owl_agent.py:
the model sees NO pixels, only rows `[id] role "name"` extracted from the live DOM, and picks elements by id.
Action (one JSON object after 'Action:'):
  {"action":"click","id":N} | {"action":"type","id":N,"text":"..."} (end text with \\n to press Enter) | {"action":"select","id":N,"option":"..."}
  {"action":"key","keys":["Enter"]} | {"action":"scroll","direction":"up|down"} | {"action":"goto","url":"..."} | {"action":"go_back"}
  {"action":"tab","index":N} | {"action":"wait"} | {"action":"done","answer":{...final response JSON...}}
Every step's (messages, response, action, rows) is appended to <rollout dir>/chat.jsonl -- the format train_grpo.py reads."""
import json, os, re, time

MAX_ROWS, HISTORY = int(os.environ.get("A11Y_MAX_ROWS", "400")), int(os.environ.get("A11Y_HISTORY", "5"))

SYSTEM = """You are an autonomous web agent operating an e-commerce store (OneStopShop). You are already logged in as emma.lopez@gmail.com
(credentials emma.lopez@gmail.com / Password.123 if you must re-authenticate; never log out or switch accounts).
You cannot see the screen; each turn you get the open tabs, the current URL, and the page as rows `[id] role "name"`.
Reply with a one-sentence Thought, then ONE line that starts with `Action:` followed by a JSON object. Example reply:
Thought: I need to open the order history.
Action: {"action": "click", "id": 12}
Available actions (JSON):
{"action": "click", "id": N}   {"action": "type", "id": N, "text": "hello"} (end the text with \\n to press Enter)   {"action": "select", "id": N, "option": "Price"}
{"action": "key", "keys": ["Enter"]}   {"action": "scroll", "direction": "down"}   {"action": "goto", "url": "http://..."}   {"action": "go_back"}
{"action": "tab", "index": N}   {"action": "wait"}
{"action": "done", "answer": {"task_type": "RETRIEVE|MUTATE|NAVIGATE", "status": "SUCCESS|NOT_FOUND_ERROR|ACTION_NOT_ALLOWED_ERROR|PERMISSION_DENIED_ERROR|DATA_VALIDATION_ERROR|UNKNOWN_ERROR", "retrieved_data": [...] or null, "error_details": null}}
Task types: RETRIEVE = the objective is to find data (retrieved_data must be a list, even for one item); MUTATE = create/update/delete state;
NAVIGATE = end on a specific page or search result (retrieved_data null). Stay on the store's domain, do not download files,
avoid changing state unless the task requires it. Always use the numeric id, never the element name."""

# DOM -> rows. Interactive elements first-class; visible text blocks (not inside an interactive element) as context rows.
EXTRACT_JS = r"""() => {
  const INTER = 'a[href],button,input:not([type=hidden]),select,textarea,summary,[role=button],[role=link],[role=tab],[role=menuitem],[role=option],[role=checkbox],[role=radio],[role=combobox],[onclick]';
  const TEXT = 'h1,h2,h3,h4,h5,h6,p,li,td,th,dt,dd,span,div,strong,em,b,label,caption,legend';
  const vis = e => { const r = e.getBoundingClientRect(), s = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0'; };
  const clean = s => (s || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-wa]').forEach(e => e.removeAttribute('data-wa'));
  const rows = [];
  for (const el of document.body ? document.body.querySelectorAll('*') : []) {
    const inter = el.matches(INTER);
    if (!inter && (!el.matches(TEXT) || (el.parentElement && el.parentElement.closest(INTER)))) continue;
    if (!vis(el)) continue;
    const tag = el.tagName.toLowerCase();
    let role, name;
    if (inter) {
      const t = (el.getAttribute('type') || '').toLowerCase();
      role = el.getAttribute('role') || ({a: 'link', button: 'button', select: 'combobox', textarea: 'textbox', summary: 'button'}[tag])
             || (tag === 'input' ? ({checkbox: 'checkbox', radio: 'radio', submit: 'button', button: 'button', search: 'searchbox'}[t] || 'textbox') : tag);
      name = clean(el.getAttribute('aria-label') || el.innerText || el.getAttribute('title') || el.getAttribute('alt') || el.getAttribute('placeholder') || el.getAttribute('name'));
      if (tag === 'input' || tag === 'textarea') { if (el.value) name += ` value="${clean(el.value).slice(0, 60)}"`; if (el.checked) name += ' [checked]'; }
      if (tag === 'select') name += ` selected="${clean(el.selectedOptions[0] ? el.selectedOptions[0].text : '')}" options=[${[...el.options].map(o => clean(o.text)).slice(0, 15).join(' | ')}]`;
    } else {
      name = clean([...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' '));
      if (!name) continue;
      role = /^h[1-6]$/.test(tag) ? 'heading' : ({td: 'cell', th: 'columnheader', li: 'listitem', label: 'label'}[tag] || 'text');
    }
    el.setAttribute('data-wa', rows.length);
    rows.push([role, name.slice(0, inter ? 120 : 200), inter ? 1 : 0]);
  }
  return rows;
}"""


def linearize(rows):
    """rows from EXTRACT_JS -> (text, kept ids). Interactive rows are kept first if the page is longer than MAX_ROWS; ids stay DOM ids."""
    idx = list(range(len(rows)))
    if len(rows) > MAX_ROWS:
        keep = [i for i in idx if rows[i][2]]
        idx = sorted(keep[:MAX_ROWS] if len(keep) >= MAX_ROWS else keep + [i for i in idx if not rows[i][2]][:MAX_ROWS - len(keep)])
    return "\n".join(f'[{i}] {rows[i][0]} "{rows[i][1]}"' for i in idx), idx


def parse(response):
    """First 'Action: {json}' only; ids may come as N, [N] or "N" (same rules as a11y_owl_agent.parse)."""
    i = response.find("Action:")
    j = response.find("{", i) if i >= 0 else -1
    act = None
    if j >= 0:
        try: act, _ = json.JSONDecoder().raw_decode(response[j:])
        except json.JSONDecodeError: act = None
    if act is None and i >= 0:
        m = re.match(r"Action:\s*(click)\W+(?:id\W*)?(\d+)", response[i:])
        if m: act = {"action": "click", "id": int(m.group(2))}
    if act is None: raise ValueError("no parsable Action")
    act["action"] = {"terminate": "done", "finish": "done", "stop": "done", "answer": "done"}.get(act.get("action"), act.get("action"))
    v = act.get("id")
    if isinstance(v, list) and v: v = v[0]
    if isinstance(v, str) and v.strip().isdigit(): v = int(v)
    if "id" in act: act["id"] = v
    return act


KEYMAP = {"ctrl": "Control", "control": "Control", "enter": "Enter", "return": "Enter", "esc": "Escape", "escape": "Escape", "tab": "Tab",
          "shift": "Shift", "alt": "Alt", "backspace": "Backspace", "delete": "Delete", "up": "ArrowUp", "down": "ArrowDown",
          "left": "ArrowLeft", "right": "ArrowRight", "pagedown": "PageDown", "pageup": "PageUp", "home": "Home", "end": "End"}


class WebAgent:
    """One rollout's policy: builds the prompt from the current page, calls the LLM, logs the step to chat.jsonl."""

    def __init__(self, client, model, task, log_path, temperature=1.0, top_p=0.9, max_tokens=512):
        self.client, self.model, self.task, self.log = client, model, task, log_path
        self.t, self.p, self.mt = temperature, top_p, max_tokens
        self.hist, self.t_reset = [], time.time()

    async def predict(self, tabs, cur, url, rows):
        t_obs = time.time()
        text, _ = linearize(rows)
        hist = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(self.hist[-HISTORY:])) or "(none)"
        tabs_s = "\n".join(f"[{i}]{' (current)' if i == cur else ''} {t}" for i, t in enumerate(tabs))
        msgs = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"Task: {self.task}\n\nOpen tabs:\n{tabs_s}\n\nCurrent URL: {url}\n\nPrevious actions:\n{hist}\n\n"
                                            f"Page elements:\n{text}\n\nNext action?"}]
        t_llm = time.time()
        r = await self.client.chat.completions.create(model=self.model, messages=msgs, temperature=self.t, top_p=self.p, max_tokens=self.mt,
                                                      extra_headers={"x-task": os.path.dirname(self.log)})
        t_llm_end = time.time(); resp = r.choices[0].message.content or ""
        try: act = parse(resp)
        except Exception as e: act = {"action": "invalid", "error": repr(e)}   # invalid output = no-op, logged
        d = act.get("id")
        self.hist.append(json.dumps(act) + (f'  [{rows[d][0]} "{rows[d][1][:60]}"]' if isinstance(d, int) and 0 <= d < len(rows) else ""))
        with open(self.log, "a") as f:
            f.write(json.dumps({"messages": msgs, "response": resp, "action": act, "url": url, "rows": rows,
                                "prompt_tokens": r.usage.prompt_tokens, "completion_tokens": r.usage.completion_tokens,
                                "t": {"reset": self.t_reset, "obs": t_obs, "llm_start": t_llm, "llm_end": t_llm_end}}) + "\n")
        return resp, act


if __name__ == "__main__":  # parser self-check
    assert parse('Thought: x\nAction: {"action": "click", "id": "7"}') == {"action": "click", "id": 7}
    assert parse('Action: {"action":"done","answer":{"task_type":"RETRIEVE","status":"SUCCESS","retrieved_data":["a"]}}')["answer"]["retrieved_data"] == ["a"]
    assert parse("Action: click id: 15") == {"action": "click", "id": 15}
    assert linearize([["link", "Home", 1], ["text", "hi", 0]])[0] == '[0] link "Home"\n[1] text "hi"'
    print("ok")
