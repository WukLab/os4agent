"""Hit-test pyautogui clicks against the AT-SPI tree; optionally snap the click to the element centre (A11Y_SNAP=1).
Returns a stable element key (role|name|ancestor path) so the same UI element matches across rollouts despite pixel noise."""
import os, re, xml.etree.ElementTree as ET
CLICK = re.compile(r"pyautogui\.(click|doubleClick|rightClick|tripleClick|moveTo)\(\s*([\d.]+)\s*,\s*([\d.]+)")
INTERACTIVE = {"push-button", "toggle-button", "menu-item", "check-menu-item", "radio-menu-item", "check-box", "radio-button", "link",
               "entry", "password-text", "combo-box", "page-tab", "list-item", "tree-item", "table-cell", "menu", "icon", "spin-button",
               "slider", "text", "paragraph", "terminal", "table-row", "column-header", "tool-bar-button"}

def _attr(e, name):  # attributes are namespaced ({ns}showing); match the local name exactly ("active" must not match "interactive")
    return next((v for k, v in e.attrib.items() if k.rsplit("}", 1)[-1] == name), None)

def _box(e):
    sc, sz = _attr(e, "screencoord"), _attr(e, "size")
    if not sc or not sz or _attr(e, "showing") == "false": return None
    a, b = re.findall(r"-?\d+", sc), re.findall(r"-?\d+", sz)
    if len(a) < 2 or len(b) < 2: return None  # some nodes carry malformed coords
    x, y, w, h = int(a[0]), int(a[1]), int(b[0]), int(b[1])
    return (x, y, w, h) if w > 0 and h > 0 else None

def occluded(root):
    """Elements of background windows that lie under the active window. AT-SPI marks every non-minimised window 'showing', so e.g. two
    maximised Chrome windows both appear in full with identical boxes; only the one with active=true is on screen. No active window -> keep all.
    Only frame/dialog windows can be behind: popups (Chrome 'alert' bubbles, menus, soffice 'window') are never active but sit on top."""
    wins = [w for app in root if app.get("name") != "gnome-shell" for w in app if _box(w)]
    top = next((_box(w) for w in wins if _attr(w, "active") == "true" and _attr(w, "window-type") != "desktop"), None)
    if not top: return set()
    tx, ty, tw, th = top
    return {e for w in wins if w.tag in ("frame", "dialog") and _attr(w, "active") != "true" for e in w.iter()
            if (b := _box(e)) and tx <= b[0] and ty <= b[1] and b[0] + b[2] <= tx + tw and b[1] + b[3] <= ty + th}

def find(tree_xml, px, py):
    if not tree_xml: return None
    best = None; root = ET.fromstring(tree_xml); hidden = occluded(root)
    def walk(e, path):
        nonlocal best
        b = _box(e); name = e.get("name", "")
        here = path + [f"{e.tag}:{name[:30]}"] if name else path
        if b and e not in hidden and b[0] <= px < b[0] + b[2] and b[1] <= py < b[1] + b[3] and e.tag in INTERACTIVE:
            a = b[2] * b[3]
            if best is None or a <= best[0]: best = (a, e.tag, name, b, "/".join(here[-4:]))
        for c in e: walk(c, here)
    walk(root, [])
    if not best: return None
    _, role, name, (x, y, w, h), path = best
    return {"role": role, "name": name, "bbox": [x, y, w, h], "center": [x + w // 2, y + h // 2], "key": f"{role}|{name}|{path}"}

def annotate(action, tree_xml):
    """-> (possibly snapped action, hit dict or None). Handles the first click-like call in the action string."""
    m = CLICK.search(action or "")
    if not m: return action, None
    px, py = float(m.group(2)), float(m.group(3))
    try: hit = find(tree_xml, px, py)
    except Exception as e: return action, {"orig_xy": [px, py], "key": None, "error": repr(e)}  # tracing must never break a rollout
    if hit is None: return action, {"orig_xy": [px, py], "key": None}
    hit["orig_xy"] = [px, py]; hit["snapped"] = False
    if os.environ.get("A11Y_SNAP") == "1":
        cx, cy = hit["center"]
        action = action[:m.start(2)] + f"{cx}, {cy}" + action[m.end(3):]; hit["snapped"] = True
    return action, hit
