"""Step 1a: can Playwright drive the Chromium 102 inside wa-shop-orig-browser over CDP? Decides option B (fork site +
browser together) vs option A (site only). Docker, no tfork.
  /mnt/data/ssd1/yutong_data/venv-rlspec/bin/python test_image.py [--keep]
Starts one container, sets the site up (base URL http://localhost, cache flush), then over CDP: form login, a category
click, a search, the agent's page-to-rows extraction (wa_agent.EXTRACT_JS), and a disconnect + reattach that must keep
the page and the login (what each copy does after a fork). Prints PASS/FAIL per check and the timings."""
import argparse, asyncio, json, subprocess, sys, time, urllib.request
from pathlib import Path

from playwright.async_api import async_playwright

sys.path.insert(0, str(Path.home() / "RL-tool-spec" / "webarena"))
from wa_agent import EXTRACT_JS  # noqa: E402  (the teammate's text agent; unchanged)

ap = argparse.ArgumentParser()
ap.add_argument("--image", default="wa-shop-orig-browser:latest")
ap.add_argument("--name", default="wa-img-test")
ap.add_argument("--site-port", type=int, default=7790)
ap.add_argument("--cdp-port", type=int, default=9290)
ap.add_argument("--keep", action="store_true", help="leave the container running")
a = ap.parse_args()
USER, PW = "emma.lopez@gmail.com", "Password.123"
MYSQL = ["mysql", "-u", "magentouser", "-pMyPassword", "magentodb", "-e"]
CDP = f"http://127.0.0.1:{a.cdp_port}"
results, T = [], {}


def sh(*cmd, check=True, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(cmd[:5])}: rc={r.returncode} {r.stderr[-400:]}")
    return r.stdout.strip()


def ex(*cmd, **kw):
    return sh("docker", "exec", a.name, *cmd, **kw)


def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def setup_site():
    t0 = time.time()
    sh("docker", "rm", "-f", a.name, check=False)
    sh("docker", "run", "-d", "--name", a.name, "--shm-size=2g", "-p", f"127.0.0.1:{a.site_port}:80",
       "-p", f"127.0.0.1:{a.cdp_port}:9222", a.image)
    for _ in range(300):
        if subprocess.run(["docker", "exec", a.name, *MYSQL, "select 1"], capture_output=True).returncode == 0:
            break
        time.sleep(2)
    T["mysql_up_s"] = time.time() - t0
    t1 = time.time()
    ex("/var/www/magento2/bin/magento", "setup:store-config:set", "--base-url=http://localhost/")
    ex(*MYSQL, "UPDATE core_config_data SET value='http://localhost/' WHERE path = 'web/secure/base_url';")
    ex("/var/www/magento2/bin/magento", "cache:flush")
    T["base_url_s"] = time.time() - t1
    t2, code = time.time(), ""
    while time.time() - t2 < 600 and code != "200":
        code = ex("curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "300", "http://localhost/", check=False)
    T["first_page_s"] = time.time() - t2
    check("site answers inside the container", code == "200", f"http {code}")
    procs = ex("ps", "-o", "pid,user,args")
    check("chromium runs under supervisord as user chrome", "chromium" in procs and "chrome" in procs,
          f"{sum('chromium' in l for l in procs.splitlines())} chromium processes")
    ver = json.loads(urllib.request.urlopen(CDP + "/json/version", timeout=10).read())
    check("CDP answers from the host", "Browser" in ver, ver.get("Browser", ""))


async def drive():
    async with async_playwright() as pw:
        t0 = time.time()
        br = await pw.chromium.connect_over_cdp(CDP, timeout=60_000)
        T["cdp_connect_s"] = time.time() - t0
        check("connect_over_cdp", br.is_connected(), f"version {br.version}, contexts {len(br.contexts)}")
        ctx = br.contexts[0]
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.set_viewport_size({"width": 1280, "height": 900})
        t1 = time.time()
        await page.goto("http://localhost/customer/account/login/", timeout=120_000)
        await page.fill("#email", USER)
        await page.fill("#pass", PW)
        await page.click("#send2", timeout=60_000)
        await page.wait_for_load_state("load", timeout=120_000)
        T["login_s"] = time.time() - t1
        body = await page.inner_text("body")
        check("form login", "Emma" in body or "My Account" in body, page.url)
        t2 = time.time()
        await page.goto("http://localhost/", timeout=120_000)
        rows = await page.evaluate(EXTRACT_JS)
        T["extract_s"] = time.time() - t2
        check("agent extraction (EXTRACT_JS) on Chromium 102", len(rows) > 50,
              f"{len(rows)} rows, e.g. {rows[3][:2] if len(rows) > 3 else rows}")
        link = page.get_by_role("link", name="Electronics").first
        await link.click(timeout=60_000)
        await page.wait_for_load_state("load", timeout=120_000)
        check("click a category link", "electronics" in page.url.lower(), page.url)
        await page.fill("#search", "headphones")
        await page.press("#search", "Enter")
        await page.wait_for_load_state("load", timeout=120_000)
        n = await page.locator(".product-item").count()
        check("search via keyboard", "catalogsearch" in page.url and n > 0, f"{n} products, {page.url}")
        await page.wait_for_load_state("networkidle", timeout=120_000)   # Magento's scripts can reset the box until idle
        # an empty plain field: Magento's search combobox keeps its query and Playwright's fill appends to it there
        # (seen with Chromium 102 and 156 alike), so it is no test of the browser
        await page.fill("#newsletter", "typed.not@submitted.com")
        await asyncio.sleep(2)
        check("typed text still there before the disconnect", await page.input_value("#newsletter") == "typed.not@submitted.com")
        url_before = page.url
        await br.close()   # over CDP this only disconnects; the browser and its pages keep running
        T["cdp_connect_2_s"] = time.time()
        br = await pw.chromium.connect_over_cdp(CDP, timeout=60_000)
        T["cdp_connect_2_s"] = time.time() - T["cdp_connect_2_s"]
        page = br.contexts[0].pages[0]
        check("reattach: same page", page.url == url_before, page.url)
        check("reattach: unsubmitted input kept", await page.input_value("#newsletter") == "typed.not@submitted.com")
        await page.goto("http://localhost/customer/account/", timeout=120_000)
        check("reattach: still logged in", "/customer/account/login" not in page.url, page.url)
        await br.close()


def main():
    try:
        setup_site()
        asyncio.run(drive())
        rss = ex("sh", "-c", "for p in $(pgrep -f chromium); do grep VmRSS /proc/$p/status; done | awk '{s+=$2} END {print s/1024}'")
        T["chromium_rss_mib"] = float(rss or 0)
    finally:
        if not a.keep:
            sh("docker", "rm", "-f", a.name, check=False)
    print(json.dumps({k: round(v, 1) for k, v in T.items()}))
    ok = all(r for _, r in results)
    print("ALL PASSED: option B" if ok else f"FAILED {[n for n, r in results if not r]}: consider option A")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
