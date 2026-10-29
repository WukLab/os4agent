"""Does a newer Chromium survive a tfork of a Magento page? The site runs in its own container (never forked); the browser
runs alone in a second container, which is the only one cloned. The site uses the host network and the browser reaches it
at its bridge gateway: on this host Docker's FORWARD policy is DROP with br_netfilter on, so container-to-container
traffic on podman's bridge is dropped (container -> host goes through INPUT, which accepts). Same browser-container settings and clone flags as
test_chrome_fork.py / test_fork.py.
  /mnt/data/ssd1/yutong_data/venv-pw1.44.0/bin/python test_browser_fork_remote.py --browser modern     (Chromium 125)
  /mnt/data/ssd1/yutong_data/venv-pw1.44.0/bin/python test_browser_fork_remote.py --browser alpine102  (control)
Source browser: log in, the product page, text typed into the newsletter field; `podman exec <browser> true`; clone
--live --copies=N; per copy: CDP reattach, typed text kept, account page, search; dmesg `trap int3` count."""
import argparse, asyncio, json, os, subprocess, time

from playwright.async_api import async_playwright

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
PODMAN = ["sudo", "-n", "env", "CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf",
          f"CONTAINERS_CONF={REPO}/agents/webarena_rl/containers-os4agent.conf", f"{REPO}/podman-tfork.sh"]
SITE_IMAGE = "localhost/wa-shop-orig-browser:latest"
BROWSERS = {   # image, chrome binary, headless flag (old headless: the one that honours --remote-debugging-address)
    "modern": ("mcr.microsoft.com/playwright/python:v1.44.0-jammy", "/ms-playwright/chromium-1117/chrome-linux/chrome",
               "--headless=old"),
    "alpine102": (SITE_IMAGE, "chromium-browser", "--headless"),
}
MYSQL = ["mysql", "-u", "magentouser", "-pMyPassword", "magentodb", "-e"]
PRODUCT = "elmwood-inn-fine-teas-orange-vanilla-caffeine-free-fruit-infusion-16-ounce-pouch.html"
TYPED = "typed.before@fork.com"
HOSTS_FIX = ("[ -s /etc/hosts ] || printf '127.0.0.1\\tlocalhost\\n::1\\tlocalhost ip6-localhost ip6-loopback\\n' "
             "> /etc/hosts")

ap = argparse.ArgumentParser()
ap.add_argument("--browser", choices=list(BROWSERS), default="modern")
ap.add_argument("--copies", type=int, default=2)
ap.add_argument("--keep", action="store_true")
a = ap.parse_args()
IMAGE, CHROME, HEADLESS = BROWSERS[a.browser]
SITE, BR = "rf-site", f"rf-br-{a.browser}"
fails, T = [], {}


def p(*args, check=True):
    r = subprocess.run([*PODMAN, *args], capture_output=True, text=True, timeout=900)
    if check and r.returncode:
        raise RuntimeError(f"podman {' '.join(args[:4])}: rc={r.returncode}\n{(r.stderr or r.stdout)[-1500:]}")
    return r.stdout.strip()


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  [{a.browser}] {name}  {detail}", flush=True)
    if not ok:
        fails.append(name)


def int3():
    return subprocess.run(["sudo", "-n", "dmesg"], capture_output=True, text=True).stdout.count("trap int3")


def ip(name):
    return p("inspect", "-f", "{{.NetworkSettings.IPAddress}}", name)


async def connect(pw, host):
    for _ in range(30):
        try:
            return await pw.chromium.connect_over_cdp(f"http://{host}:9222", timeout=20_000)
        except Exception:
            await asyncio.sleep(2)
    raise RuntimeError(f"no CDP at {host}")


async def step(name, coro):
    try:
        r = await asyncio.wait_for(coro, 120)
        check(name, True, str(r)[:80] if r is not None else "")
        return r
    except Exception as e:
        check(name, False, str(e).splitlines()[0][:120])


def start_site(url):
    """The Magento container on the host network, base URL = the browser container's gateway."""
    p("rm", "-f", SITE, check=False)
    p("run", "-d", "--name", SITE, "--network", "host", "--shm-size=2g", SITE_IMAGE)
    for _ in range(300):
        if subprocess.run([*PODMAN, "exec", SITE, *MYSQL, "select 1"], capture_output=True).returncode == 0:
            break
        time.sleep(2)
    p("exec", SITE, "/var/www/magento2/bin/magento", "setup:store-config:set", f"--base-url={url}")
    p("exec", SITE, *MYSQL, f"UPDATE core_config_data SET value='{url}' WHERE path = 'web/secure/base_url';")
    p("exec", SITE, "/var/www/magento2/bin/magento", "cache:flush")
    return url


async def main():
    kids = []
    try:
        p("rm", "-f", BR, check=False)
        p("run", "-d", "--name", BR, "--cgroupns=host", "--ulimit", "nofile=1048576:1048576", "--security-opt",
          "seccomp=unconfined", "--security-opt", "label=disable", "--shm-size=2g", "--tmpfs", "/tmp:size=1g",
          "--entrypoint", "sh", IMAGE, "-c",
          f"exec {CHROME} {HEADLESS} --no-sandbox --disable-gpu --no-first-run --remote-debugging-address=0.0.0.0 "
          "--remote-debugging-port=9222 --user-data-dir=/tmp/profile about:blank")
        url = f"http://{p('inspect', '-f', '{{.NetworkSettings.Gateway}}', BR)}/"
        t0 = time.time()
        start_site(url)
        T["site_setup_s"] = time.time() - t0
        async with async_playwright() as pw:
            br = await connect(pw, ip(BR))
            check("browser version", True, br.version)
            page = br.contexts[0].pages[0]
            await page.goto(url + "customer/account/login/", timeout=120_000)
            await page.fill("#email", "emma.lopez@gmail.com"); await page.fill("#pass", "Password.123")
            await page.click("#send2", timeout=60_000); await page.wait_for_load_state("load")
            await page.goto(url + PRODUCT, timeout=120_000); await page.wait_for_load_state("networkidle")
            await page.fill("#newsletter", TYPED); await asyncio.sleep(1)
            check("source: logged in, product page, typed text", await page.input_value("#newsletter") == TYPED, page.url)
            await br.close()
            p("exec", BR, "true"); time.sleep(0.1)
            before = int3()
            t1 = time.time()
            out = p("container", "clone", "--live", f"--copies={a.copies}", "--persistent=async", "--tfork-tcp-close",
                    f"--tfork-ghost-limit={64 << 20}", "--tfork-overlay-btrfs", "--name", f"{BR}-k", BR)
            kids = [f"{BR}-k-{i}" for i in range(a.copies)]
            T["clone_s"] = time.time() - t1
            check(f"clone --live --copies={a.copies} (browser container only)",
                  len([l for l in out.splitlines() if len(l.strip()) == 64]) == a.copies, f"{T['clone_s']:.1f} s")
            time.sleep(3)
            for k in kids:
                p("exec", k, "sh", "-c", HOSTS_FIX, check=False)
                br = await connect(pw, ip(k))
                pg = br.contexts[0].pages[0]
                check(f"{k}: reattach finds the product page", PRODUCT in pg.url, pg.url)
                await step(f"{k}: typed text kept", pg.input_value("#newsletter"))
                await step(f"{k}: account page", pg.goto(url + "customer/account/", timeout=120_000))
                await step(f"{k}: search", pg.goto(url + "catalogsearch/result/?q=tea", timeout=120_000))
                await step(f"{k}: new tab + product page", (await br.contexts[0].new_page()).goto(url + PRODUCT, timeout=120_000))
                await br.close()
            T["int3_new"] = int3() - before
            check("no Chromium CHECK crash (dmesg trap int3)", T["int3_new"] == 0, f"{T['int3_new']} new")
    finally:
        if not a.keep:
            p("rm", "-f", "-t", "0", BR, *kids, SITE, check=False)
    print(json.dumps(T))
    print("ALL PASSED" if not fails else f"FAILED: {fails}")


if __name__ == "__main__":
    asyncio.run(main())
