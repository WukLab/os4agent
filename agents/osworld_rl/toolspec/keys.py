"""Action identity: type + target element role|name + argument. Element ids are renumbered per page, so the
element's name is used instead; URLs drop the host (each site slot has its own port)."""

from __future__ import annotations

import json
from urllib.parse import urlsplit

FINAL = {"done"}


def path_of(url: str) -> str:
    u = urlsplit(url or "")
    return u.path + (f"?{u.query}" if u.query else "")


def arg_of(a: dict) -> str:
    kind = a.get("action")
    if kind == "type":
        return json.dumps(str(a.get("text", "")))
    if kind == "select":
        return json.dumps(str(a.get("option", "")))
    if kind == "goto":
        return path_of(str(a.get("url", "")))
    if kind == "key":
        return str(a.get("keys", ""))
    if kind == "scroll":
        return str(a.get("direction", ""))
    if kind == "tab":
        return str(a.get("index", ""))
    return ""


def action_key(act: dict, hit: dict | None) -> str | None:
    """None for the final `done`. hit: the target row as wa_run.py logs it, or None."""
    kind = act.get("action")
    if kind in FINAL:
        return None
    target = (hit or {}).get("key") or (f"#{act['id']}" if "id" in act else "")
    return " ".join(x for x in (kind, target, arg_of(act)) if x)
