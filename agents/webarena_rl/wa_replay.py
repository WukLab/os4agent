"""Replay recorded WebArena-Lite rollouts (wa_record.py) on forked environments: per task group one source environment
is set up as in the recording (container, MySQL, base URL + cache flush, first page, CDP, login, start URL(s)), then
live-cloned with tfork into one copy per rollout; each copy replays its rollout's recorded actions, with the recorded
model time slept in place of the model call (x --replay-latency), while page reads, actions, settle waits and the fork
are measured fresh. No GPU. Runs as root (like wa_record.py).
  sudo -n /mnt/data/ssd1/yutong_data/venv-pw1.44.0/bin/python wa_replay.py --result-dir /mnt/data/btrfs/wa_replay/<run> \
      [--trace-dir .../lite32_h100_r3 --redo-dir .../lite32_h100_r3_redo] [--tasks 29] [--groups-at-once 4]
Image: wa-shop-browser142 (Chromium 142; forked Chromium 102 renderers crash, NOTES.md). The traces were recorded with
Chromium 102, so every step compares the page rows read now with the recorded ones (fidelity), and the final reward
with the recorded reward.
Memory (--sample-s): per environment the container's own cgroup (memory.current and memory.stat: anon, file,
active_file, inactive_file, shmem, kernel, file_mapped; ws = current - inactive_file) and PSS over its processes; also the
common parent cgroup of all environments (shared pages a copy reads are charged to the cgroup that first touched them,
usually the source, so only the parent total and the sum are comparable across systems). Host MemAvailable is kept
for reference only: evictable page cache makes it drift.
Outputs in --result-dir: config.json, events.jsonl (run / wave / setup / clone / rollout events), mem.jsonl,
<task>__g<k>/steps.jsonl (per step: obs / sleep / act / settle times, recorded times, row match), result.json."""
import argparse, asyncio, json, os, re, subprocess, sys, time
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(Path("/home/yutong/RL-tool-spec/webarena"))]
import lite_eval  # noqa: E402
from wa_agent import EXTRACT_JS, KEYMAP  # noqa: E402  (teammate's agent, unchanged)

TR = "/mnt/data/btrfs/wa_traces"
ap = argparse.ArgumentParser()
ap.add_argument("--result-dir", required=True)
ap.add_argument("--trace-dir", default=f"{TR}/lite32_h100_r3")
ap.add_argument("--redo-dir", default=f"{TR}/lite32_h100_r3_redo", help="re-recorded rollouts; they replace the trace dir's")
ap.add_argument("--tasks", default="", help="Lite task ids (default: the recording's config.json task_ids)")
ap.add_argument("--rollouts", type=int, default=8)
ap.add_argument("--schedule", choices=["groups", "waves"], default="groups",
                help="groups: as agents/osworld_rl/osw_run.py, every task group runs its own lifecycle (set up, fork, "
                     "replay, score, tear down) and frees its environments when it ends; --parallel groups live at once. "
                     "waves: synchronous waves of --groups-at-once groups, freed together at the wave's end (as recorded)")
ap.add_argument("--parallel", type=int, default=0, help="groups schedule: task groups live at once (0 = all)")
ap.add_argument("--groups-at-once", type=int, default=4, help="waves schedule: task groups per wave (as recorded)")
ap.add_argument("--setup-concurrency", type=int, default=0, help="environments setting up at once (0 = no limit)")
ap.add_argument("--clone-concurrency", type=int, default=4, help="clones running at once (osw_run.py --fork-concurrency)")
ap.add_argument("--mem-limit-gib", type=float, default=220, help="stop the run (kill every environment) when host used "
                "memory passes this (0 = off)")
ap.add_argument("--clone-retries", type=int, default=4, help="as osw_run.py: 5 attempts, backoff 20, 40, 60, 80 s")
ap.add_argument("--system", choices=["tfork", "criu", "aenv"], default="tfork",
                help="tfork: one live clone of N copies | criu: N serial full dump + restore clones (osw_run.py's CKPT) | "
                     "aenv: AgentENV microVMs, source from the template, copies from its fork API (aenv_env.py)")
ap.add_argument("--aenv-template", default="wa-shop142", help="setup/aenv/make_template.sh")
ap.add_argument("--aenv-cli", default="/home/yutong/.local/bin/aenv")
ap.add_argument("--aenv-home", default="/home/yutong", help="HOME for the aenv CLI (its ~/.config/aenv/credentials)")
ap.add_argument("--aenv-key", default="/mnt/data/btrfs/aenv/env/secrets/api-key")
ap.add_argument("--replay-latency", type=float, default=1.0, help="x recorded model time slept per step (0 = none)")
ap.add_argument("--sleep-after-action", type=float, default=1.0)
ap.add_argument("--step-timeout", type=float, default=120, help="page read / action limit (s); scoring gets 5x")
ap.add_argument("--action-timeout", type=float, default=0, help="one Playwright limit (s) for every action (click, fill, "
                "select, Enter, goto, go_back); 0 = the agent's own (wa_run.py: 5 s, 30 s for goto / go_back / Enter), "
                "as recorded")
ap.add_argument("--sample-s", type=float, default=5.0)
ap.add_argument("--image", default="localhost/wa-shop-browser142:latest")
ap.add_argument("--limit-waves", type=int, default=0)
ap.add_argument("--keep", action="store_true", help="leave the containers running (debug)")
ap.add_argument("--remap-ids", type=int, default=1, help="when the row at the recorded element id differs, act on the "
                "nearest row with the recorded (role, name)")
a = ap.parse_args()

REPO = HERE.parent.parent
PODMAN = ["env", "CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf",
          f"CONTAINERS_CONF={HERE}/containers-os4agent.conf", str(REPO / "podman-tfork.sh")]
MYSQL = ["mysql", "-u", "magentouser", "-pMyPassword", "magentodb", "-e"]
HOSTS_FIX = ("[ -s /etc/hosts ] || printf '127.0.0.1\\tlocalhost\\n::1\\tlocalhost ip6-localhost ip6-loopback\\n' "
             "> /etc/hosts")
RELAY = ["/opt/chr/bin/socat", "tcp-listen:9222,fork,reuseaddr", "tcp:127.0.0.1:9221"]
OUT = Path(a.result_dir)
OUT.mkdir(parents=True, exist_ok=True)
TASKS = lite_eval.load_tasks()
RUN = OUT.name.replace("_", "-")[:30]
LIVE = {}          # container name -> (init pid, group label, role)
ENDED = []         # containers of finished waves (killed, removed after the run)
BUNDLE_DIRS = []   # tfork bundles of successful clones (removed after their copies)
BUNDLES = "/mnt/data/btrfs/podman/storage/tfork-bundles"
AENV = None
if a.system == "aenv":
    import aenv_env  # noqa: E402
    AENV = aenv_env.Aenv(a.aenv_cli, a.aenv_home, a.aenv_template, a.aenv_key)
SETUP_SEM = asyncio.Semaphore(a.setup_concurrency or 10**6)
CLONE_SEM = asyncio.Semaphore(a.clone_concurrency)


def now():
    return time.time()


def jl(path, rec):
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def event(kind, **kw):
    rec = {"t": now(), "event": kind, **kw}
    print(json.dumps(rec)[:300], flush=True)
    jl(OUT / "events.jsonl", rec)


async def pod(*args, check=True, timeout=900):
    p = await asyncio.create_subprocess_exec(*PODMAN, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(p.communicate(), timeout)
    except asyncio.TimeoutError:
        p.kill()
        raise RuntimeError(f"podman {' '.join(args[:3])} timed out")
    if check and p.returncode:
        raise RuntimeError(f"podman {' '.join(args[:3])}: rc={p.returncode} {err.decode()[-800:]}")
    return out.decode().strip()


def load_trace(task_id, k):
    """Recorded rollout: (result.json, chat.jsonl records, steps.jsonl records); the redo dir wins."""
    for root in (a.redo_dir, a.trace_dir):
        d = Path(root) / f"{task_id}__g{k}"
        if root and (d / "result.json").exists():
            rd = lambda f: [json.loads(l) for l in open(d / f) if l.strip()]
            return json.loads((d / "result.json").read_text()), rd("chat.jsonl"), rd("steps.jsonl"), str(d)
    raise FileNotFoundError(f"no trace for {task_id}__g{k}")


# ---------------------------------------------------------------- memory (cgroups first)

CG_KEYS = ("anon", "file", "active_file", "inactive_file", "shmem", "kernel", "file_mapped", "file_dirty")


def cg_path(pid):
    return "/sys/fs/cgroup" + open(f"/proc/{pid}/cgroup").read().strip().split("::", 1)[1]


def cg_read(d):
    st = {l.split()[0]: int(l.split()[1]) for l in open(f"{d}/memory.stat")}
    cur = int(open(f"{d}/memory.current").read())
    r = {"cg_mib": round(cur / 2**20, 1), "cg_ws_mib": round((cur - st.get("inactive_file", 0)) / 2**20, 1),
         **{f"cg_{k}_mib": round(st.get(k, 0) / 2**20, 1) for k in CG_KEYS}}
    try:
        r["cg_peak_mib"] = round(int(open(f"{d}/memory.peak").read()) / 2**20, 1)
    except OSError:
        pass
    return r


def smaps(pids):
    tot = dict.fromkeys(("Rss", "Pss", "Pss_Anon", "Pss_File", "Pss_Shmem"), 0)
    for pid in pids:
        try:
            for line in open(f"/proc/{pid}/smaps_rollup"):
                k, _, v = line.partition(":")
                if k in tot:
                    tot[k] += int(v.split()[0])
        except (OSError, ValueError):
            pass
    return {f"{k.lower()}_mib": round(v / 1024, 1) for k, v in tot.items()}


async def sample_memory():
    while True:
        try:
            ns = {}
            for p in filter(str.isdigit, os.listdir("/proc")):
                try:
                    ns.setdefault(os.readlink(f"/proc/{p}/ns/pid"), []).append(int(p))
                except OSError:
                    pass
            per, cgs = {}, {}
            for name, (pid, grp, role) in list(LIVE.items()):
                try:
                    if isinstance(pid, tuple):   # AENV: the VMM process holds the guest RAM; no per-VM cgroup
                        per[name] = {**smaps([pid[1]]), "group": grp, "role": role, "vm": pid[1]}
                        continue
                    d = cg_path(pid)
                    per[name] = {**smaps(ns.get(os.readlink(f"/proc/{pid}/ns/pid"), [])), **cg_read(d), "group": grp,
                                 "role": role, "cg": d[len("/sys/fs/cgroup"):]}
                    cgs[d] = per[name]
                except OSError:
                    pass
            # sums over distinct cgroups (a copy could share its source's cgroup); the common parent's own counters
            tot = {k: round(sum(c.get(k, 0) for c in cgs.values()), 1)
                   for k in ("cg_mib", "cg_ws_mib", *(f"cg_{x}_mib" for x in CG_KEYS))}
            tot.update({k: round(sum(c.get(k, 0) for c in per.values()), 1) for k in ("pss_mib", "rss_mib")})
            tot["distinct_cgroups"] = len(cgs)
            parent = {}
            if cgs:
                pp = os.path.commonpath(list(cgs))
                if pp in cgs:
                    pp = os.path.dirname(pp)
                parent = {"cg": pp[len("/sys/fs/cgroup"):], **cg_read(pp)}
            m = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
            extra = {"aenv_server": cg_read(AENV.server_cgroup())} if AENV else {}
            jl(OUT / "mem.jsonl", {"t": now(), "envs": len(per), "total": tot, "parent": parent, "containers": per, **extra,
                                   "host": {"used_mib": (m["MemTotal"] - m["MemAvailable"]) // 1024,
                                            "cached_mib": m["Cached"] // 1024, "anon_mib": m["AnonPages"] // 1024},
                                   "load1": os.getloadavg()[0]})
        except Exception as e:
            print("mem sampler:", e, flush=True)
        await asyncio.sleep(a.sample_s)


# ---------------------------------------------------------------- environment (as wa_record.py)

async def ex(name, *cmd, check=True, timeout=900):
    """Run cmd in an environment (podman exec, or aenv exec in a VM) -> stdout."""
    if AENV:
        return (await AENV.exec(name, *cmd, check=check, timeout=timeout))[1]
    return await pod("exec", name, *cmd, check=check, timeout=timeout)


async def ex_ok(name, *cmd):
    if AENV:
        return (await AENV.exec(name, *cmd, check=False, timeout=120))[0] == 0
    p = await asyncio.create_subprocess_exec(*PODMAN, "exec", name, *cmd, stdout=asyncio.subprocess.DEVNULL,
                                             stderr=asyncio.subprocess.DEVNULL)
    return await p.wait() == 0


async def setup_src_aenv(label):
    """A source VM from the template (the site is already running in its snapshot), then the same setup steps."""
    tm = {"t_start": now()}
    async with SETUP_SEM:
        tm["t_setup_slot"] = now()
        sb, vmm = await AENV.start()
        tm["t_container_up"] = now()
        LIVE[sb] = (("vm", vmm), label, "src")
        for _ in range(300):
            if await ex_ok(sb, *MYSQL, "select 1"):
                break
            await asyncio.sleep(2)
        tm["t_mysql_up"] = now()
        await ex(sb, "/var/www/magento2/bin/magento", "setup:store-config:set", "--base-url=http://localhost/")
        await ex(sb, *MYSQL, "UPDATE core_config_data SET value='http://localhost/' WHERE path = 'web/secure/base_url';")
        await ex(sb, "/var/www/magento2/bin/magento", "cache:flush")
        tm["t_base_url_done"] = now()
        code = await ex(sb, "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "300",
                        "http://localhost/", check=False)
        tm["t_first_page"], tm["first_page_http"] = now(), code
    return sb, AENV.addr(sb), tm


async def setup_src(name, label):
    """-> (environment name, CDP host:port, timing)"""
    if AENV:
        return await setup_src_aenv(label)
    tm = {"t_start": now()}
    async with SETUP_SEM:
        tm["t_setup_slot"] = now()
        await pod("rm", "-f", "-t", "0", name, check=False)
        # test_fork.py's source flags (passed with 142): /tmp on tmpfs, shared memory in /dev/shm
        await pod("run", "-d", "--name", name, "--cgroupns=host", "--ulimit", "nofile=1048576:1048576", "--security-opt",
                  "seccomp=unconfined", "--security-opt", "label=disable", "--shm-size=2g", "--tmpfs", "/tmp:size=1g",
                  a.image)
        tm["t_container_up"] = now()
        r = json.loads(await pod("inspect", name))[0]
        LIVE[name] = (r["State"]["Pid"], label, "src")
        ip = r["NetworkSettings"]["IPAddress"]
        for _ in range(300):
            p = await asyncio.create_subprocess_exec(*PODMAN, "exec", name, *MYSQL, "select 1",
                                                     stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            if await p.wait() == 0:
                break
            await asyncio.sleep(2)
        tm["t_mysql_up"] = now()
        await pod("exec", name, "/var/www/magento2/bin/magento", "setup:store-config:set", "--base-url=http://localhost/")
        await pod("exec", name, *MYSQL, "UPDATE core_config_data SET value='http://localhost/' WHERE path = 'web/secure/base_url';")
        await pod("exec", name, "/var/www/magento2/bin/magento", "cache:flush")
        tm["t_base_url_done"] = now()
        code = await pod("exec", name, "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "300",
                         "http://localhost/", check=False)
        tm["t_first_page"], tm["first_page_http"] = now(), code
    return name, f"{ip}:9222", tm


async def connect(pw, addr, tries=60):
    for _ in range(tries):
        try:
            return await pw.chromium.connect_over_cdp(f"http://{addr}", timeout=20_000)
        except Exception:
            await asyncio.sleep(2)
    raise RuntimeError(f"no CDP at {addr}")


async def prepare_browser(pw, ip, task, tm):
    """Login and start URL(s) in the source's Chromium, then disconnect (the pages stay; the copies inherit them)."""
    br = await connect(pw, ip)
    tm["t_cdp"] = now()
    ctx = br.contexts[0]
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.set_viewport_size({"width": 1280, "height": 900})
    await page.goto("http://localhost/customer/account/login/", timeout=120_000)
    await page.fill("#email", "emma.lopez@gmail.com")
    await page.fill("#pass", "Password.123")
    await page.click("#send2", timeout=60_000)
    await page.wait_for_load_state("load", timeout=120_000)
    tm["t_login_done"] = now()
    urls = [u.strip().replace("__SHOPPING__", lite_eval.SHOPPING) for u in task["start_url"].split("|AND|")]
    pages = [page] + [await ctx.new_page() for _ in urls[1:]]
    for pg, u in zip(pages, urls):
        await pg.goto(u, timeout=120_000)
    await pages[0].bring_to_front()
    await br.close()
    tm["t_ready"] = now()


def drop_bundle(b):
    """Remove a kept (PODMAN_TFORK_NO_REAP) bundle: its copies' overlay mounts (rootfs-<i>) are still mounted and
    snap-ro is a read-only btrfs subvolume, so umount, delete the subvolume, then rm."""
    ms = [l.split()[4] for l in open("/proc/self/mountinfo") if l.split()[4].startswith(b + "/")]
    for m in sorted(ms, reverse=True):
        if subprocess.run(["umount", m]).returncode:
            subprocess.run(["umount", "-l", m])
    if os.path.isdir(f"{b}/snap-ro"):
        subprocess.run(["btrfs", "subvolume", "delete", f"{b}/snap-ro"], capture_output=True)
    subprocess.run(["rm", "-rf", "--one-file-system", b])


async def clone_once(src, name, flags, n):
    """One `container clone --live` making n copies, up to --clone-retries + 1 attempts with osw_run.py's backoff
    (20, 40, 60, 80 s). PODMAN_TFORK_NO_REAP keeps the clone's bundle (CRIU logs; for tfork it also holds the copies'
    live root filesystems, so it is removed after the copies). A failed attempt: podman's stderr and the CRIU logs go
    to clone_fail/, its partial copies are removed. The bundle is found from the copy's io.podman.tfork.batch-id
    annotation (clones may run concurrently), or for a failed clone from podman's error. -> (copy names, t0, t1, attempt)"""
    for attempt in range(a.clone_retries + 1):
        if attempt:
            await asyncio.sleep(20 * attempt)
        t0 = now()
        p = await asyncio.create_subprocess_exec(
            *PODMAN[:1], "PODMAN_TFORK_NO_REAP=1", *PODMAN[1:], "container", "clone", "--live", *flags,
            "--name", name, src, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await p.communicate()
        t1 = now()
        out, err = out.decode(), err.decode()
        ids = [l.strip() for l in out.splitlines() if len(l.strip()) == 64]
        m = re.search(r"(/[^ ]*/tfork-bundles/[0-9a-f]+)/crun-tfork.log", err)
        b = m.group(1) if m else None
        if p.returncode == 0 and len(ids) == n:
            names = []
            for cid in ids:
                r = json.loads(await pod("inspect", cid))[0]
                names.append(r["Name"].lstrip("/"))
                b = f"{BUNDLES}/{r['Config']['Annotations'].get('io.podman.tfork.batch-id', '')}"
            if b and os.path.isdir(b) and b not in BUNDLE_DIRS:
                BUNDLE_DIRS.append(b)
            return names, t0, t1, attempt
        d = OUT / "clone_fail" / f"{name}_try{attempt}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "podman_stderr.txt").write_text(f"rc={p.returncode}\n{out}\n{err}")
        if b:
            subprocess.run(["sh", "-c", f"cp {b}/crun-tfork.log {b}/img/*.log {d}/ 2>/dev/null"])
        event("clone_failed", src=src, name=name, attempt=attempt, rc=p.returncode, copies=len(ids),
              secs=round(t1 - t0, 2), logs=str(d), err=err[-400:])
        partial = [x for x in (await pod("ps", "-a", "--format", "{{.Names}}", check=False)).split()
                   if x.startswith(name + "-")]
        if partial:
            await pod("rm", "-f", "-t", "0", *partial, check=False)
        if b:
            drop_bundle(b)
    raise RuntimeError(f"clone {name} of {src} failed {a.clone_retries + 1} times; logs in {OUT / 'clone_fail'}")


async def fork(src, n, label):
    """-> copy names, their IPs, timing; each copy's /etc/hosts and CDP relay fixed.
    tfork: one live clone of n copies (test_fork.py / osw_run.py flags, overlay rootfs).
    criu: osw_run.py's CKPT, n serial single-copy clones, each a full dump + restore with --tfork-full-memcopy
    (nothing shared with the source); each copy counts as live (memory) as soon as it exists."""
    if AENV:   # no fixup: the VM's own processes (CDP relay included) survive the VM fork
        async with CLONE_SEM:
            t0 = now()
            kids, fork_s, pair_s = await AENV.fork(src, n)
            t1 = now()
        for k in kids:
            LIVE[k] = (("vm", AENV.pid[k]), label, "copy")
        event("clone_done", src=src, system=a.system, copies=n, clone_s=round(t1 - t0, 2), fork_api_s=round(fork_s, 2),
              pair_s=round(pair_s, 2), attempt=0)
        return kids, [AENV.addr(k) for k in kids], {"t_clone_start": t0, "t_clone_end": t1, "t_fixup_end": t1,
                                                    "attempt": 0, "fork_api_s": fork_s, "pair_s": pair_s, "system": a.system}
    ghost = f"--tfork-ghost-limit={64 << 20}"
    async with CLONE_SEM:
        await pod("exec", src, "true")
        await asyncio.sleep(0.1)   # let tini reap exec children before the freeze
        if a.system == "tfork":
            kids, t0, t1, attempt = await clone_once(src, f"{src}-k", [f"--copies={n}", "--persistent=async",
                                                     "--tfork-tcp-close", ghost, "--tfork-overlay-btrfs"], n)
            per_copy = [round(t1 - t0, 2)]
        else:
            kids, per_copy, attempt, t0 = [], [], 0, now()
            for i in range(n):
                names, c0, c1, att = await clone_once(src, f"{src}-k{i}", ["--copies=1", "--persistent=sync",
                                                      "--tfork-tcp-close", ghost, "--tfork-full-memcopy"], 1)
                r = json.loads(await pod("inspect", names[0]))[0]
                LIVE[names[0]] = (r["State"]["Pid"], label, "copy")
                kids += names
                per_copy.append(round(c1 - c0, 2))
                attempt = max(attempt, att)
            t1 = now()
    ips = []
    for kname in kids:
        r = json.loads(await pod("inspect", kname))[0]
        LIVE[kname] = (r["State"]["Pid"], label, "copy")
        ips.append(f'{r["NetworkSettings"]["IPAddress"]}:9222')
        await pod("exec", kname, "sh", "-c", HOSTS_FIX)
        # the relay dies at the fork and copies have no supervisord socket
        await pod("exec", kname, "sh", "-c", "pkill -f '[s]ocat tcp-listen:9222' ; true")
        await pod("exec", "-d", kname, *RELAY)
    t2 = now()
    event("clone_done", src=src, system=a.system, copies=n, clone_s=round(t1 - t0, 2), fixup_s=round(t2 - t1, 2),
          attempt=attempt, per_copy_s=per_copy)
    return kids, ips, {"t_clone_start": t0, "t_clone_end": t1, "t_fixup_end": t2, "attempt": attempt,
                       "per_copy_s": per_copy, "system": a.system}


SHORT_MS = int(a.action_timeout * 1000) or 5000    # click / fill / select (wa_run.py: 5 s)
LONG_MS = int(a.action_timeout * 1000) or 30000    # goto / go_back / Enter (wa_run.py: 30 s; Enter had the default 30 s)
if a.action_timeout:   # a type step is fill + Enter: room for both inside the step guard
    a.step_timeout = max(a.step_timeout, 2 * a.action_timeout + 30)


async def execute(ctx, cur, act):
    """wa_run.py's execute (as wa_record.py); its timeouts, or --action-timeout for all of them. -> current tab index"""
    page, kind = ctx.pages[cur], act.get("action")
    loc = lambda: page.locator(f'[data-wa="{int(act["id"])}"]').first
    before = len(ctx.pages)
    if kind == "click": await loc().click(timeout=SHORT_MS)
    elif kind == "type":
        t = str(act.get("text", "")); await loc().fill(t.rstrip("\n"), timeout=SHORT_MS)
        if t.endswith("\n"): await loc().press("Enter", timeout=LONG_MS)
    elif kind == "select":
        try: await loc().select_option(label=str(act.get("option")), timeout=SHORT_MS)
        except Exception: await loc().select_option(value=str(act.get("option")), timeout=SHORT_MS)
    elif kind == "key": await page.keyboard.press("+".join(KEYMAP.get(str(k).lower(), str(k)) for k in act.get("keys", [])))
    elif kind == "scroll": await page.mouse.wheel(0, -600 if act.get("direction") == "up" else 600)
    elif kind == "goto": await page.goto(str(act["url"]), timeout=LONG_MS)
    elif kind == "go_back": await page.go_back(timeout=LONG_MS)
    elif kind == "tab":
        i = int(act.get("index", cur))
        if not 0 <= i < len(ctx.pages): raise ValueError(f"no tab {i}")
        cur = i; await ctx.pages[cur].bring_to_front()
    elif kind in ("wait", "invalid"): await asyncio.sleep(1)
    else: raise ValueError(f"unknown action {kind}")
    if len(ctx.pages) > before: cur = len(ctx.pages) - 1
    return cur


async def read_page(page, ctx, tries=3):
    for i in range(tries):
        try:
            rows = await page.evaluate(EXTRACT_JS)
            return rows, [f"{await p.title()} ({p.url})" for p in ctx.pages]
        except Exception as e:
            if i == tries - 1 or "context was destroyed" not in str(e):
                raise
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception:
                pass


def lite_answer(act):
    ans = act.get("answer")
    if isinstance(ans, dict):
        data = ans.get("retrieved_data")
        if isinstance(data, list) and data:
            return ", ".join(str(x) for x in data)
        return str(ans.get("status") or "")
    return "" if ans is None else str(ans)


def row_match(rec, now_rows, act):
    """Fidelity of one page read vs the recording: exact rows, row count, the acted-on row."""
    now_rows = json.loads(json.dumps(now_rows))
    i = act.get("id")
    tgt = None
    if isinstance(i, int):
        tgt = 0 <= i < len(rec) and 0 <= i < len(now_rows) and rec[i][:2] == now_rows[i][:2]
    diff = [[j, rec[j] if j < len(rec) else None, now_rows[j] if j < len(now_rows) else None]
            for j in range(max(len(rec), len(now_rows))) if (rec[j:j + 1] or None) != (now_rows[j:j + 1] or None)]
    return {"rows_equal": rec == now_rows, "rows_rec": len(rec), "rows_now": len(now_rows), "target_equal": tgt,
            "rows_diff_n": len(diff), "rows_diff": diff[:6]}


# ---------------------------------------------------------------- one replayed rollout

async def replay(pw, task, k, name, ip, wave_start, fork_tm):
    d = OUT / f"{task['task_id']}__g{k}"
    d.mkdir(parents=True, exist_ok=True)
    rec_res, chat, rsteps, src_dir = load_trace(task["task_id"], k)
    res = {"task_id": task["task_id"], "k": k, "container": name, "trace": src_dir, "fork": fork_tm,
           "t_wave_start": wave_start, "reward_rec": rec_res.get("reward"), "steps_rec": rec_res.get("steps")}
    br = None
    try:
        br = await connect(pw, ip)
        ctx = br.contexts[0]
        res["t_cdp"] = now()
        await ctx.pages[0].set_viewport_size({"width": 1280, "height": 900})
        res["t_rollout_start"] = now()
        cur, answer = 0, None
        for c, rs in zip(chat, rsteps):
            act = c["action"]
            s = {"step": c["step"], "t_obs_start": now(), "action": act}
            page = ctx.pages[cur]
            s["url_before"], s["url_rec"] = page.url, c["url"]
            # step timeouts: a hung browser (CRIU run, 120__g1: CDP stopped answering) fails the rollout, not the run
            rows, _ = await asyncio.wait_for(read_page(page, ctx), a.step_timeout)
            s["t_obs_end"] = now()
            s.update(row_match(c["rows"], rows, act))
            if s["target_equal"] is False and a.remap_ids:   # page varied (row added / reordered): act on the same element
                i, want = act["id"], c["rows"][act["id"]][:2] if 0 <= act["id"] < len(c["rows"]) else None
                js = [j for j, r in enumerate(rows) if want and list(r[:2]) == list(want)]
                if js:
                    act = {**act, "id": min(js, key=lambda j: abs(j - i))}
                    s["remapped"] = [i, act["id"]]
                else:
                    s["remapped"] = [i, None]
            s["llm_rec_s"] = c["t"]["llm_end"] - c["t"]["llm_start"]
            s["rec"] = {k2: rs.get(k2) for k2 in ("t_obs_start", "t_obs_end", "t_llm_send", "t_first_token", "t_llm_done",
                                                  "t_act_start", "t_act_end", "t_settle_end", "error", "url_after")}
            s["t_llm_send"] = now()
            await asyncio.sleep(a.replay_latency * s["llm_rec_s"])
            s["t_llm_done"] = now()
            if act.get("action") == "done":
                answer = act
                s["t_act_start"] = s["t_act_end"] = s["t_settle_end"] = now()
                jl(d / "steps.jsonl", s)
                break
            s["t_act_start"] = now()
            try:
                cur = await asyncio.wait_for(execute(ctx, cur, act), a.step_timeout)
            except asyncio.TimeoutError:
                raise RuntimeError(f"step {c['step']}: action timed out after {a.step_timeout} s")
            except Exception as e:
                s["error"] = repr(e)[:300]
            s["t_act_end"] = now()
            try:
                await ctx.pages[cur].wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception:
                pass
            await asyncio.sleep(a.sleep_after_action)
            s["t_settle_end"], s["url_after"] = now(), ctx.pages[cur].url
            s["url_after_equal"] = s["url_after"] == rs.get("url_after")
            jl(d / "steps.jsonl", s)
        res.update(t_rollout_end=now(), steps=len(chat), answer=answer)
        res["t_eval_start"] = now()
        try:
            res["reward"] = await asyncio.wait_for(lite_eval.evaluate(task, lite_answer(answer or {}), ctx.pages[cur]),
                                                   5 * a.step_timeout)
        except Exception as e:
            res["reward"], res["eval_error"] = None, repr(e)[:300]
        res["t_eval_end"] = now()
    except Exception as e:
        res["error"] = repr(e)[:500]
    finally:
        if br:
            try:
                await br.close()
            except Exception:
                pass
    (d / "result.json").write_text(json.dumps(res, indent=1, default=str))
    event("rollout_done", task=task["task_id"], k=k, reward=res.get("reward"), reward_rec=res["reward_rec"],
          error=res.get("error"), secs=round(res.get("t_rollout_end", now()) - res.get("t_rollout_start", now()), 1))
    return res


# ---------------------------------------------------------------- waves

async def group(pw, wi, task):
    tid, label = task["task_id"], f"w{wi}-t{task['task_id']}"
    src = f"wa-{RUN}-w{wi}-t{tid}"
    src, addr, tm = await setup_src(src, label)
    await prepare_browser(pw, addr, task, tm)
    kids, ips, ftm = await fork(src, a.rollouts, label)
    (OUT / f"src_{tid}.json").write_text(json.dumps({"src": src, "setup": tm, "fork": ftm, "copies": kids}, indent=1))
    return src, kids, ips, ftm


async def wave(pw, wi, tasks):
    event("wave_setup_start", wave=wi, tasks=[t["task_id"] for t in tasks])
    gs = await asyncio.gather(*(group(pw, wi, t) for t in tasks), return_exceptions=True)
    event("wave_setup_done", wave=wi, failed=sum(isinstance(g, Exception) for g in gs),
          errors=[repr(g)[:300] for g in gs if isinstance(g, Exception)][:3])
    wave_start = now()
    names = [f"wa-{RUN}-w{wi}-t{t['task_id']}" for t in tasks]
    try:
        await asyncio.gather(*(replay(pw, t, k, kids[k], ips[k], wave_start, ftm)
                               for t, g in zip(tasks, gs) if not isinstance(g, Exception)
                               for _, kids, ips, ftm in [g] for k in range(a.rollouts)), return_exceptions=True)
    finally:
        event("wave_rollouts_done", wave=wi)
        for g in gs:
            if not isinstance(g, Exception):
                names += g[1]
        for n in names:
            LIVE.pop(n, None)
    if not a.keep:   # kill now, remove after the run (podman removal is slow and serial, as in wa_record.py)
        await pod("kill", "-s", "KILL", *names, check=False)
    event("wave_teardown_done", wave=wi, envs=len(names))
    ENDED.extend(names)


async def group_lifecycle(pw, gi, task, par):
    """osw_run.py's group: set up the source, fork, replay the rollouts, tear down (kill) as soon as they end."""
    tid, label = task["task_id"], f"g{gi}-t{task['task_id']}"
    src, kids = f"wa-{RUN}-g{gi}-t{tid}", []
    async with par:
        event("group_start", group=gi, task=tid)
        try:
            src, addr, tm = await setup_src(src, label)
            event("group_setup_done", group=gi, task=tid, src=src, secs=round(now() - tm["t_start"], 1))
            await prepare_browser(pw, addr, task, tm)
            kids, ips, ftm = await fork(src, a.rollouts, label)
            (OUT / f"src_{tid}.json").write_text(json.dumps({"src": src, "setup": tm, "fork": ftm, "copies": kids}, indent=1))
            start = now()
            await asyncio.gather(*(replay(pw, task, k, kids[k], ips[k], start, ftm) for k in range(a.rollouts)),
                                 return_exceptions=True)
        except Exception as e:
            event("group_error", group=gi, task=tid, error=repr(e)[:400])
        finally:
            names = [src, *kids]
            for n in names:
                LIVE.pop(n, None)
            if a.keep:
                pass
            elif AENV:   # VMs are removed right away (aenv rm), nothing left for the end of the run
                await AENV.rm(names)
            else:
                await pod("kill", "-s", "KILL", *names, check=False)
                ENDED.extend(names)
            event("group_done", group=gi, task=tid, envs=len(names))


async def mem_guard():
    while a.mem_limit_gib:
        m = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
        used = (m["MemTotal"] - m["MemAvailable"]) / 2**20
        if used > a.mem_limit_gib:
            event("mem_limit", used_gib=round(used, 1), limit_gib=a.mem_limit_gib, live=len(LIVE))
            if AENV:
                for n in list(LIVE):
                    subprocess.run([a.aenv_cli, "rm", n], capture_output=True, env=AENV.env)
            else:
                subprocess.run([*PODMAN, "kill", "-s", "KILL", *LIVE], capture_output=True)
            (OUT / "ended_containers.txt").write_text("\n".join([*ENDED, *LIVE]) + "\n")
            os._exit(3)
        await asyncio.sleep(1)


async def main():
    cfg = json.loads((Path(a.trace_dir) / "config.json").read_text())
    ids = [int(x) for x in a.tasks.split(",")] if a.tasks else cfg["task_ids"]
    (OUT / "config.json").write_text(json.dumps({**vars(a), "task_ids": ids}, indent=1))
    extra = {}
    if AENV:   # AENV needs io_uring and its server; the aenv-server cgroup's idle charge is the run's baseline
        if open("/proc/sys/kernel/io_uring_disabled").read().strip() != "0":
            raise SystemExit("aenv: kernel.io_uring_disabled must be 0 (setup/aenv/start-server.sh)")
        extra = {"aenv_template": a.aenv_template, "aenv_baseline": cg_read(AENV.server_cgroup())}
    event("run_start", tasks=len(ids), rollouts=a.rollouts, image=a.image, replay_latency=a.replay_latency,
          schedule=a.schedule, parallel=a.parallel, system=a.system, **extra)
    bg = [asyncio.create_task(sample_memory()), asyncio.create_task(mem_guard())]
    async with async_playwright() as pw:
        if a.schedule == "groups":
            par = asyncio.Semaphore(a.parallel or len(ids))
            await asyncio.gather(*(group_lifecycle(pw, gi, TASKS[t], par) for gi, t in enumerate(ids)))
        else:
            waves = [ids[i:i + a.groups_at_once] for i in range(0, len(ids), a.groups_at_once)]
            for wi, w in enumerate(waves[:a.limit_waves or None]):
                await wave(pw, wi, [TASKS[t] for t in w])
    (OUT / "ended_containers.txt").write_text("\n".join(ENDED) + "\n")
    for b in bg:
        b.cancel()
    if not a.keep and ENDED:
        t0 = now()
        ended = set(ENDED)
        for _ in range(5):   # podman's database lock races the killed containers' own cleanup: repeat until none left
            left = [n for n in (await pod("ps", "-a", "--format", "{{.Names}}", check=False)).split() if n in ended]
            if not left:
                break
            await pod("rm", "-f", "-t", "0", *left, check=False, timeout=7200)
        for b in BUNDLE_DIRS:   # after the copies are gone
            drop_bundle(b)
        event("removed", n=len(ENDED), bundles=len(BUNDLE_DIRS), secs=round(now() - t0, 1))
    event("run_done")
    if os.environ.get("SUDO_UID"):
        subprocess.run(["chown", "-R", f"{os.environ['SUDO_UID']}:{os.environ['SUDO_GID']}", str(OUT)])


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGHUP, signal.SIG_IGN)
    asyncio.run(main())
