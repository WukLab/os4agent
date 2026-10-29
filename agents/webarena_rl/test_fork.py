"""Step 3 smoke: live-clone one WebArena environment (site + Chromium, wa-shop-orig-browser) with tfork and check the
copies. Podman through this checkout's podman-tfork.sh, storage on /mnt/data/btrfs (needs sudo -n).
  /mnt/data/ssd1/yutong_data/venv-pw1.44.0/bin/python test_fork.py [--copies 2] [--keep]
Source container as agents/osworld_rl/osw_run.py starts one (cgroupns=host, nofile 1048576, unconfined seccomp,
label=disable, shm 2g, bridge network). Setup: base URL http://localhost, cache flush, login over CDP, a product page,
text typed into the newsletter field (not submitted). Fork: `podman exec <src> true`, then
`container clone --live --copies=N --persistent=async --tfork-tcp-close --tfork-ghost-limit=64M --tfork-overlay-btrfs`
(osw_run.py's tfork flags), then each copy's /etc/hosts refilled (osw_run.py's HOSTS_FIX). Checks per copy: site
answers; CDP reattach finds the page and the typed text; still logged in; search (Elasticsearch); a wishlist write
(MySQL) stays private to that copy. Memory (PSS / RSS over the container's processes, cgroup memory.current) before
and after the fork."""
import argparse, asyncio, json, os, subprocess, sys, time

from playwright.async_api import async_playwright

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
PODMAN = ["sudo", "-n", "env", "CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf",
          f"CONTAINERS_CONF={REPO}/agents/webarena_rl/containers-os4agent.conf", f"{REPO}/podman-tfork.sh"]
IMAGE = "localhost/wa-shop-orig-browser:latest"
MYSQL = ["mysql", "-u", "magentouser", "-pMyPassword", "magentodb", "-e"]
HOSTS_FIX = ("[ -s /etc/hosts ] || printf '127.0.0.1\\tlocalhost\\n::1\\tlocalhost ip6-localhost ip6-loopback\\n' "
             "> /etc/hosts")
PRODUCT = "http://localhost/elmwood-inn-fine-teas-orange-vanilla-caffeine-free-fruit-infusion-16-ounce-pouch.html"
TYPED = "typed.before@fork.com"

ap = argparse.ArgumentParser()
ap.add_argument("--copies", type=int, default=2)
ap.add_argument("--name", default="wa-fork-src")
ap.add_argument("--keep", action="store_true")
ap.add_argument("--park-url", default="", help="navigate the source's page here right before the fork (diagnosis)")
ap.add_argument("--chrome-extra", default="", help="extra Chromium flags, appended to the supervisord command line")
ap.add_argument("--dev-shm", type=int, default=1, help="restart Chromium without --disable-dev-shm-usage (shared memory in "
                "/dev/shm, a tmpfs) and mount /tmp as tmpfs; 0 = the image's settings")
ap.add_argument("--log-tag", default="", help="save the clone's CRIU logs to "
                "/mnt/data/ssd4/yutong/tfork_build/clone_logs/<tag>/ and remove its bundle")
ap.add_argument("--image", default=IMAGE, help="e.g. localhost/wa-shop-browser142:latest (Chromium 142 baked in)")
ap.add_argument("--chrome-bundle", default="", help="tar from setup/build_chromium_bundle.sh: installed into the source "
                "container, supervisord's Chromium becomes /opt/chr/chromium/chromium --headless=old")
ap.add_argument("--bundle-headless", default="--headless",
                help="headless flag for the bundle: --headless=old for 131 (the last with old headless), --headless after")
ap.add_argument("--type-mode", choices=["fill", "keyboard"], default="fill",
                help="keyboard: click + keyboard.type (the Chromium 131 bundle's renderer segfaults on fill)")
ap.add_argument("--seccomp", choices=["unconfined", "nopkey"], default="unconfined",
                help="nopkey: agents/osworld_rl/seccomp_nopkey.json (pkey_alloc fails with ENOSPC, so Chromium / V8 run "
                     "without memory protection keys)")
a = ap.parse_args()
fails, T, BUNDLE = [], {}, []
SECCOMP = "unconfined" if a.seccomp == "unconfined" else os.path.join(REPO, "agents/osworld_rl/seccomp_nopkey.json")


def int3():
    return subprocess.run(["sudo", "-n", "dmesg"], capture_output=True, text=True).stdout.count("trap int3")


def pkey_vmas(name):
    """Per Chromium process in the container: (type, VMAs with ProtectionKey != 0, all VMAs), from /proc/<pid>/smaps."""
    _, pid = info(name)
    out = subprocess.run(["sudo", "-n", sys.executable, "-I", "-c", f"""
import os, re
ns = os.readlink('/proc/{pid}/ns/pid')
for d in sorted(os.listdir('/proc'), key=lambda x: (not x.isdigit(), x)):
    try:
        if not d.isdigit() or os.readlink(f'/proc/{{d}}/ns/pid') != ns: continue
        cmd = open(f'/proc/{{d}}/cmdline').read().split(chr(0))
        if 'chrom' not in cmd[0]: continue
        t = next((c[7:] for c in cmd if c.startswith('--type=')), 'browser')
        keys = re.findall(r'^ProtectionKey:\\s+(\\d+)', open(f'/proc/{{d}}/smaps').read(), re.M)
        print(t, sum(k != '0' for k in keys), len(keys))
    except OSError: pass
"""], capture_output=True, text=True).stdout.split("\n")
    return [l for l in out if l]


def p(*args, check=True, timeout=900, keep_bundle=False):
    # keep the clone's bundle (logs) and log CRIU at debug level (default: errors only, which hides pkey_state's lines)
    cmd = [*PODMAN[:3], "PODMAN_TFORK_NO_REAP=1", "CRIU_TFORK_LOG_LEVEL=4", *PODMAN[3:]] if keep_bundle else PODMAN
    r = subprocess.run([*cmd, *args], capture_output=True, text=True, timeout=timeout)
    if check and r.returncode:
        raise RuntimeError(f"podman {' '.join(args[:4])}: rc={r.returncode}\n{(r.stderr or r.stdout)[-2000:]}")
    return r.stdout.strip()


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)
    if not ok:
        fails.append(name)


def info(name):
    r = json.loads(p("inspect", name))[0]
    return r["NetworkSettings"]["IPAddress"], r["State"]["Pid"]


def mem(name):
    """PSS / RSS summed over the container's pid namespace and its cgroup's memory.current (MiB)."""
    _, pid = info(name)
    out = subprocess.run(["sudo", "-n", sys.executable, "-I", "-c", f"""
import os, json
ns = os.readlink('/proc/{pid}/ns/pid'); tot = {{'Pss': 0, 'Rss': 0, 'Pss_Anon': 0, 'Pss_File': 0, 'Pss_Shmem': 0}}; n = 0
for q in filter(str.isdigit, os.listdir('/proc')):
    try:
        if os.readlink(f'/proc/{{q}}/ns/pid') != ns: continue
        for l in open(f'/proc/{{q}}/smaps_rollup'):
            k, _, v = l.partition(':')
            if k in tot: tot[k] += int(v.split()[0])
        n += 1
    except OSError: pass
d = '/sys/fs/cgroup' + open('/proc/{pid}/cgroup').read().strip().split('::', 1)[1]
print(json.dumps({{**{{k.lower() + '_mib': round(v / 1024) for k, v in tot.items()}}, 'procs': n,
                  'cg_mib': round(int(open(d + '/memory.current').read()) / 2**20)}}))"""], capture_output=True, text=True)
    return json.loads(out.stdout) if out.returncode == 0 else {"error": out.stderr[-300:]}


def site_ok(name):
    return p("exec", name, "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "120", "http://localhost/",
             check=False) == "200"


async def attach(ip):
    pw = await async_playwright().start()
    for _ in range(30):
        try:
            return pw, await pw.chromium.connect_over_cdp(f"http://{ip}:9222", timeout=30_000)
        except Exception:
            await asyncio.sleep(2)
    raise RuntimeError(f"no CDP at {ip}")


async def put_text(page, sel, text):
    """fill(), or click + keyboard.type (--type-mode keyboard); 60 s cap: after a renderer crash keyboard.type never returns."""
    if a.type_mode == "keyboard":
        await page.click(sel, timeout=60_000); await asyncio.wait_for(page.keyboard.type(text), 60)
    else:
        await page.fill(sel, text, timeout=60_000)


async def setup_source():
    t0 = time.time()
    p("rm", "-f", a.name, check=False)
    tmp = ["--tmpfs", "/tmp:size=1g"] if a.dev_shm else []
    p("run", "-d", "--name", a.name, "--cgroupns=host", "--ulimit", "nofile=1048576:1048576", "--security-opt",
      f"seccomp={SECCOMP}", "--security-opt", "label=disable", "--shm-size=2g", *tmp, a.image)
    if a.dev_shm:   # Chromium's shared memory in /dev/shm instead of deleted files in /tmp (CRIU ghost files)
        p("exec", a.name, "sed", "-i", "s/ --disable-dev-shm-usage//", "/etc/supervisor.d/chromium.ini")
        if a.chrome_extra:
            p("exec", a.name, "sed", "-i", f"s|  --window-size=1280,900 about:blank|  --window-size=1280,900 {a.chrome_extra} about:blank|",
              "/etc/supervisor.d/chromium.ini")
        if a.chrome_bundle:
            p("cp", a.chrome_bundle, f"{a.name}:/chr.tar")
            p("exec", a.name, "sh", "-c", "tar -C / -xf /chr.tar && rm /chr.tar && sed -i "
              f"'s|^command=chromium-browser --headless |command=/opt/chr/chromium/chromium {a.bundle_headless} |; "
              "s|--remote-debugging-port=9222|--remote-debugging-port=9221|; "
              # own profile: the image's Chromium 102 already made /tmp/chrome-profile at boot, and 131 started on it
              # wedges (CDP hangs, a renderer segfaults); a fresh profile starts clean
              "s|--user-data-dir=/tmp/chrome-profile|--user-data-dir=/tmp/chrome-profile-bundle|; "
              # supervisord's user= keeps HOME=/root: 142's crashpad handler then has no database and Chromium exits
              "s|^user=chrome|user=chrome\\nenvironment=HOME=\\\"/home/chrome\\\"|' /etc/supervisor.d/chromium.ini && "
              "printf '[program:cdp-relay]\\ncommand=/opt/chr/bin/socat tcp-listen:9222,fork,reuseaddr tcp:127.0.0.1:9221\\n"
              "autostart=true\\nautorestart=true\\n' > /etc/supervisor.d/cdp-relay.ini && supervisorctl reread")
        p("exec", a.name, "supervisorctl", "update", "chromium")
        if a.chrome_bundle:
            p("exec", a.name, "supervisorctl", "update", "cdp-relay")
        await asyncio.sleep(3)
        check("chromium restarted without --disable-dev-shm-usage",
              "disable-dev-shm" not in p("exec", a.name, "sh", "-c", "ps -o args | grep -E '[c]hromium-browser|[/]chrome |/opt/chr/chromium/[c]hromium'"))
    for _ in range(300):
        if subprocess.run([*PODMAN, "exec", a.name, *MYSQL, "select 1"], capture_output=True).returncode == 0:
            break
        await asyncio.sleep(2)
    T["src_mysql_up_s"] = time.time() - t0
    p("exec", a.name, "/var/www/magento2/bin/magento", "setup:store-config:set", "--base-url=http://localhost/")
    p("exec", a.name, *MYSQL, "UPDATE core_config_data SET value='http://localhost/' WHERE path = 'web/secure/base_url';")
    p("exec", a.name, "/var/www/magento2/bin/magento", "cache:flush")
    check("source site answers", site_ok(a.name))
    ip, _ = info(a.name)
    pw, br = await attach(ip)
    T["browser_version"] = br.version
    page = br.contexts[0].pages[0]
    await page.goto("http://localhost/customer/account/login/", timeout=120_000)
    await put_text(page, "#email", "emma.lopez@gmail.com"); await put_text(page, "#pass", "Password.123")
    await page.click("#send2", timeout=60_000); await page.wait_for_load_state("load")
    await page.goto(PRODUCT, timeout=120_000); await page.wait_for_load_state("networkidle")
    await put_text(page, "#newsletter", TYPED); await asyncio.sleep(1)
    check("source: logged in, product page, typed text", await page.input_value("#newsletter") == TYPED, page.url)
    if a.park_url:
        await page.goto(a.park_url, timeout=60_000); await asyncio.sleep(2)
        check(f"source parked on {a.park_url}", page.url.rstrip("/") == a.park_url.rstrip("/"), page.url)
    await br.close(); await pw.stop()
    T["src_setup_s"] = time.time() - t0


async def check_copy(name, k):
    p("exec", name, "sh", "-c", HOSTS_FIX)
    if a.chrome_bundle or a.image != IMAGE:   # the CDP relay dies at the fork (osw_run.py's relay_restart); copies have no supervisord socket
        p("exec", name, "sh", "-c", "pkill -f '[s]ocat tcp-listen:9222' ; true")
        p("exec", "-d", name, "/opt/chr/bin/socat", "tcp-listen:9222,fork,reuseaddr", "tcp:127.0.0.1:9221")
        await asyncio.sleep(1)
    check(f"{name}: site answers", site_ok(name))
    ip, _ = info(name)
    pw, br = await attach(ip)
    page = br.contexts[0].pages[0]
    check(f"{name}: CDP reattach finds the page", page.url.rstrip("/") == (a.park_url or PRODUCT).rstrip("/"), page.url)
    if not a.park_url:
        check(f"{name}: typed text survived the fork", await page.input_value("#newsletter") == TYPED)
    await page.goto("http://localhost/customer/account/", timeout=120_000)
    check(f"{name}: still logged in", "/customer/account/login" not in page.url, page.url)
    await page.goto("http://localhost/catalogsearch/result/?q=tea", timeout=120_000)
    n = await page.locator(".product-item").count()
    check(f"{name}: search works (Elasticsearch)", n > 0, f"{n} products")
    if k == 0:   # a write in copy 0 only
        await page.goto(PRODUCT, timeout=120_000); await page.wait_for_load_state("networkidle")
        await page.click("a.action.towishlist", timeout=60_000); await page.wait_for_load_state("load")
    await page.goto("http://localhost/wishlist/", timeout=120_000)
    has = "Elmwood Inn" in (await page.inner_text("body"))
    check(f"{name}: wishlist {'has' if k == 0 else 'does not have'} the item (writes stay private)", has == (k == 0))
    await br.close(); await pw.stop()


async def main():
    kids = []
    try:
        await setup_source()
        T["mem_src_before"] = mem(a.name)
        T["pkey_vmas_src"] = pkey_vmas(a.name)
        T["int3_before"] = int3()
        p("exec", a.name, "true"); time.sleep(0.1)   # let tini reap exec children before the freeze (osw_run.py)
        t0 = time.time()
        try:
            out = p("container", "clone", "--live", f"--copies={a.copies}", "--persistent=async", "--tfork-tcp-close",
                    f"--tfork-ghost-limit={64 << 20}", "--tfork-overlay-btrfs", "--name", f"{a.name}-k", a.name,
                    keep_bundle=True)
        except RuntimeError as e:
            import re
            m = re.search(r"(/[^ ]*/tfork-bundles/[0-9a-f]+)/crun-tfork.log", str(e))
            if m:
                dest = f"/mnt/data/ssd4/yutong/tfork_build/failed_clones/{os.path.basename(m.group(1))[:16]}"
                subprocess.run(["sudo", "-n", "sh", "-c", f"mkdir -p {dest} && cp {m.group(1)}/crun-tfork.log "
                                f"{m.group(1)}/img/*.log {dest}/ 2>/dev/null; chown -R {os.getuid()} {dest}"])
                print("failed clone logs saved to", dest)
            raise
        T["clone_s"] = time.time() - t0
        if a.log_tag:   # the bundle this clone made: the newest one, created after t0
            root = "/mnt/data/btrfs/podman/storage/tfork-bundles"
            ls = subprocess.run(["sudo", "-n", "find", root, "-mindepth", "1", "-maxdepth", "1", "-type", "d", "-newermt",
                                 f"@{int(t0) - 1}", "-printf", "%T@ %p\\n"], capture_output=True, text=True).stdout.split("\n")
            b = sorted(l for l in ls if l)[-1].split()[1] if any(ls) else None
            dest = f"/mnt/data/ssd4/yutong/tfork_build/clone_logs/{a.log_tag}"
            if b:   # CRIU's logs only: the bundle also holds the copies' live root filesystems (remove it after them)
                subprocess.run(["sudo", "-n", "sh", "-c", f"mkdir -p {dest}/img && cp {b}/crun-tfork.log {dest}/ ; "
                                f"cp {b}/img/*.log {dest}/img/ ; chown -R {os.getuid()} {dest}"])
                BUNDLE.append(b)
            T["clone_logs"] = dest if b else "no bundle found"
        kids = [f"{a.name}-k-{i}" for i in range(a.copies)]
        check(f"clone --live --copies={a.copies}", len([l for l in out.splitlines() if len(l.strip()) == 64]) == a.copies,
              f"{T['clone_s']:.1f} s")
        time.sleep(5)
        T["mem_after_fork"] = {n: mem(n) for n in [a.name, *kids]}
        T["pkey_vmas_after_fork"] = {n: pkey_vmas(n) for n in kids}
        check("source still serves after the fork", site_ok(a.name))
        for k, name in enumerate(kids):
            try:
                await check_copy(name, k)
            except Exception as e:
                check(f"{name}: checks ran to the end", False, repr(e)[:300])
        T["mem_after_checks"] = {n: mem(n) for n in [a.name, *kids]}
        T["int3_new"] = int3() - T["int3_before"]
        check("no Chromium CHECK crash (dmesg trap int3)", T["int3_new"] == 0, f"{T['int3_new']} new")
    finally:
        if not a.keep:
            p("rm", "-f", "-t", "0", a.name, *kids, check=False)
            for b in BUNDLE:   # after the copies are gone
                subprocess.run(["sudo", "-n", "rm", "-rf", "--one-file-system", b])
    print(json.dumps(T, indent=1))
    print("ALL PASSED" if not fails else f"FAILED: {fails}")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    asyncio.run(main())
