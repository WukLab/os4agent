"""Does a forked Chromium renderer survive navigation? Same test for any browser, without Magento: a tiny local site
(two pages, an input; python3 -m http.server :8000 in the container) and a headless Chromium with CDP on :9222.
  /mnt/data/ssd1/yutong_data/venv-pw1.44.0/bin/python test_chrome_fork.py --browser modern    (Chromium 125)
  /mnt/data/ssd1/yutong_data/venv-pw1.44.0/bin/python test_chrome_fork.py --browser alpine102 (our image's Chromium 102)
Source container with test_fork.py's settings (cgroupns=host, nofile 1048576, unconfined seccomp, label=disable, shm 2g,
tmpfs /tmp); type into the input on a.html; `podman exec src true`; clone --live --copies=2 with osw_run.py's tfork
flags; per copy: CDP reattach, typed text kept, reload, navigate to b.html, new tab; dmesg `trap int3` count."""
import argparse, asyncio, json, os, subprocess, sys, time

from playwright.async_api import async_playwright

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
PODMAN = ["sudo", "-n", "env", "PODMAN_TFORK_NO_REAP=1", "CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf",
          f"CONTAINERS_CONF={REPO}/agents/webarena_rl/containers-os4agent.conf", f"{REPO}/podman-tfork.sh"]
BROWSERS = {   # image, chrome binary, headless flag (old headless: the one that honours --remote-debugging-address)
    "modern": ("mcr.microsoft.com/playwright/python:v1.44.0-jammy", "/ms-playwright/chromium-1117/chrome-linux/chrome",
               "--headless=old"),
    "alpine102": ("localhost/wa-shop-orig-browser:latest", "chromium-browser", "--headless"),
}
SITE = ("mkdir -p /tmp/site && cd /tmp/site && "
        "printf '<html><body><a id=b href=b.html>to b</a> <input id=f></body></html>' > a.html && "
        "printf '<html><body><p id=p>page b</p></body></html>' > b.html && "
        "(python3 -m http.server 8000 > /tmp/http.log 2>&1 &) && ")
TYPED = "typed before the fork"
ANIMATED = ("mkdir -p /tmp/site && cd /tmp/site && "
            "printf '<html><head><style>@keyframes s{from{transform:rotate(0)}to{transform:rotate(360deg)}} "
            "#d{width:80px;height:80px;background:red;animation:s 1s linear infinite}</style></head><body>"
            "<div id=d></div><a id=b href=b.html>to b</a> <input id=f><p id=n></p><script>let i=0;"
            "(function t(){n.textContent=i++;requestAnimationFrame(t)})()"
            "</script></body></html>' > a.html && "
            "printf '<html><body><p id=p>page b</p></body></html>' > b.html && "
            "(python3 -m http.server 8000 > /tmp/http.log 2>&1 &) && ")

ap = argparse.ArgumentParser()
ap.add_argument("--browser", choices=list(BROWSERS), default="modern")
ap.add_argument("--keep", action="store_true")
ap.add_argument("--page", choices=["static", "animated", "magento"], default="static",
                help="animated: a.html runs a CSS animation and a requestAnimationFrame loop; magento: the browser is on the "
                     "WebArena product page (alpine102 only: the site is started too)")
a = ap.parse_args()
IMAGE, CHROME, HEADLESS = BROWSERS[a.browser]
NAME = f"chrome-fork-{a.browser}"
fails = []


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
        r = await asyncio.wait_for(coro, 60)
        check(name, True, str(r)[:60] if r is not None else "")
        return r
    except Exception as e:
        check(name, False, str(e).splitlines()[0][:100])


async def main():
    kids = []
    p("rm", "-f", NAME, check=False)
    p("run", "-d", "--name", NAME, "--cgroupns=host", "--ulimit", "nofile=1048576:1048576", "--security-opt",
      "seccomp=unconfined", "--security-opt", "label=disable", "--shm-size=2g", "--tmpfs", "/tmp:size=1g",
      "--entrypoint", "sh", IMAGE, "-c",
      (ANIMATED if a.page == "animated" else SITE) + f"exec {CHROME} {HEADLESS} --no-sandbox --disable-gpu --no-first-run --remote-debugging-address=0.0.0.0 "
      "--remote-debugging-port=9222 --user-data-dir=/tmp/profile about:blank")
    try:
        async with async_playwright() as pw:
            br = await connect(pw, ip(NAME))
            check("browser version", True, br.version)
            page = br.contexts[0].pages[0]
            await page.goto("http://localhost:8000/a.html")
            await page.fill("#f", TYPED)
            if a.page == "animated":
                c1 = await page.inner_text("#n"); await asyncio.sleep(0.5); c2 = await page.inner_text("#n")
                check("animation loop runs before the fork", c1 != c2 and c2 != "", f"{c1} -> {c2}")
            await br.close()
            p("exec", NAME, "true"); time.sleep(0.1)
            before = int3()
            t0 = time.time()
            out = p("container", "clone", "--live", "--copies=2", "--persistent=async", "--tfork-tcp-close",
                    f"--tfork-ghost-limit={64 << 20}", "--tfork-overlay-btrfs", "--name", f"{NAME}-k", NAME)
            kids = [f"{NAME}-k-{i}" for i in range(2)]
            check("clone --live --copies=2", len([l for l in out.splitlines() if len(l.strip()) == 64]) == 2,
                  f"{time.time() - t0:.1f} s")
            time.sleep(3)
            for k in kids:
                br = await connect(pw, ip(k))
                pg = br.contexts[0].pages[0]
                await step(f"{k}: reattach, typed text kept", pg.input_value("#f")) if True else None
                if (await pg.input_value("#f")) != TYPED:
                    check(f"{k}: typed text is the source's", False)
                await step(f"{k}: reload", pg.reload())
                await step(f"{k}: navigate to b.html", pg.goto("http://localhost:8000/b.html"))
                await step(f"{k}: new tab", br.contexts[0].new_page())
                await br.close()
            check("no Chromium CHECK crash (dmesg trap int3)", int3() == before, f"{int3() - before} new")
    finally:
        if not a.keep:
            p("rm", "-f", "-t", "0", NAME, *kids, check=False)
    print("ALL PASSED" if not fails else f"FAILED: {fails}")


if __name__ == "__main__":
    asyncio.run(main())
