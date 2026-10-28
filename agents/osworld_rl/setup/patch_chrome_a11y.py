"""Idempotent: add --force-renderer-accessibility to every `google-chrome` launch in OSWorld task configs so web-page content appears in the AT-SPI tree.
  python patch_chrome_a11y.py <OSWorld dir>      (originals saved as *.json.orig)"""
import glob, json, shutil, sys
n = 0
def fix(o):
    global n
    if isinstance(o, dict):
        c = o.get("command")
        if isinstance(c, list) and c and c[0] in ("google-chrome", "chromium", "chromium-browser", "google-chrome-stable") and "--force-renderer-accessibility" not in c:
            c.insert(1, "--force-renderer-accessibility"); n += 1
        for v in o.values(): fix(v)
    elif isinstance(o, list):
        for v in o: fix(v)
for p in glob.glob(f"{sys.argv[1]}/evaluation_examples/examples/*/*.json"):
    ex = json.load(open(p)); before = n; fix(ex)
    if n != before:
        shutil.copyfile(p, p + ".orig") if not glob.glob(p + ".orig") else None
        json.dump(ex, open(p, "w"), indent=2)
print(f"patched {n} chrome launches")
