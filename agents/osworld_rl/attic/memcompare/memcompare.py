#!/usr/bin/env python3
"""Memory footprint of fork-for-branching on an OSWorld desktop:
os4agent TFORK vs stock CRIU (checkpoint + N restores) vs AENV (Firecracker fork).

Same image, same desktop start script, same scripted trajectory (no LLM):
  prefix  -> runs on the source (Chromium tabs + LibreOffice Calc with data)
  fork N
  branch  -> runs on every child, with per-branch input (diverging writes)
Memory = sum of PSS over every host process backing the source + children
(container processes for podman, firecracker VMMs for AENV), split into
anon / file / shmem, sampled after prefix, after fork, after branch.

Run as root:  sudo python3 memcompare.py --systems tfork,criu,aenv --n 4
Dev check (no root, docker, no fork): python3 memcompare.py --validate-docker
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
IMAGE = "ghcr.io/wuklab/webtop:ubuntu-kde"

# Desktop without s6 /init (AENV boots its own init), identical on every system.
DESK = r"""
export DISPLAY=:1
H=/config; mkdir -p $H/.XDG $H/Desktop /tmp/.X11-unix; chmod 1777 /tmp/.X11-unix
if [ "$(id -u)" = 0 ]; then chown -R abc:abc $H; AS="runuser -u abc --"; else AS=""; fi
Xvfb :1 -screen 0 1920x1080x24 -nolisten tcp >/tmp/xvfb.log 2>&1 &
for i in $(seq 100); do xdpyinfo >/dev/null 2>&1 && break; sleep 0.1; done
$AS env HOME=$H DISPLAY=:1 XDG_RUNTIME_DIR=$H/.XDG bash /defaults/startwm.sh >/tmp/wm.log 2>&1 &
wait
"""
READY = "pgrep -x plasmashell >/dev/null && pgrep -x kwin_x11 >/dev/null && DISPLAY=:1 xdpyinfo >/dev/null 2>&1"


def as_desktop(cmd: str) -> str:
    """Run cmd as the desktop user with the X env, from root or not."""
    env = "env HOME=/config DISPLAY=:1 XDG_RUNTIME_DIR=/config/.XDG"
    inner = f"{env} bash -c {shlex.quote(cmd)}"
    return f'if [ "$(id -u)" = 0 ]; then runuser -u abc -- {inner}; else {inner}; fi'


def bg(cmd: str) -> str:
    return f"setsid nohup {cmd} >/dev/null 2>&1 < /dev/null &"


def pyauto(code: str) -> str:
    return "python3 -c " + shlex.quote("import pyautogui, time; pyautogui.PAUSE=0.02\n" + code)


def calc_rows(tag: str, rows: int) -> str:
    # one Calc row per iteration: tag, i, i^2, i^3
    return pyauto("pyautogui.press('esc')\n"
                  f"for i in range({rows}):\n"
                  f"    pyautogui.write('{tag}\\t%d\\t%d\\t%d' % (i, i*i, i**3), interval=0)\n"
                  "    pyautogui.press('enter'); pyautogui.press('home')")


FOCUS_CALC = ("for w in $(xdotool search --name 'Tip of the Day'); do xdotool windowclose $w; done; "
              "xdotool search --name 'LibreOffice Calc' windowactivate --sync 2>/dev/null; sleep 0.5")

PREFIX = [  # (desc, shell cmd as desktop user, settle seconds)
    ("chromium 3 tabs", bg("/usr/local/bin/wrapped-chromium --no-first-run --disable-gpu "
                           "file:///usr/share/doc/ file:///etc/ file:///usr/share/"), 12),
    ("calc open", bg("libreoffice --calc --norestore"), 15),
    ("calc type 300 rows", f"{FOCUS_CALC}; {calc_rows('src', 300)}", 3),
]


def branch_steps(i: int):
    return [
        ("calc type 200 rows", f"{FOCUS_CALC}; {calc_rows(f'b{i}', 200)}", 2),
        ("chromium new tab", bg(f"/usr/local/bin/wrapped-chromium file:///usr/lib/?b={i}"), 8),
    ]


# ---------------------------------------------------------------- memory

SMAPS = ("Rss", "Pss", "Pss_Anon", "Pss_File", "Pss_Shmem")


def smaps(pids: list[int]) -> dict:
    tot = dict.fromkeys(SMAPS, 0)
    n = 0
    for pid in pids:
        try:
            for line in Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines():
                k, _, v = line.partition(":")
                if k in tot:
                    tot[k] += int(v.split()[0])
            n += 1
        except (OSError, ValueError):
            continue
    out = {k.lower() + "_mib": round(v / 1024, 1) for k, v in tot.items()}
    out["nprocs"] = n
    out["host_avail_mib"] = meminfo()["MemAvailable"] // 1024
    return out


def meminfo() -> dict:
    return {l.split(":")[0]: int(l.split()[1]) for l in Path("/proc/meminfo").read_text().splitlines()}


def pidns_members(pid: int) -> list[int]:
    try:
        ns = os.readlink(f"/proc/{pid}/ns/pid")
    except OSError:
        return []
    out = []
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if os.readlink(f"/proc/{p}/ns/pid") == ns:
                    out.append(int(p))
            except OSError:
                pass
    return out


def sh(argv, check=True, **kw):
    r = subprocess.run(argv, capture_output=True, text=True, **kw)
    if check and r.returncode != 0:
        raise RuntimeError(f"{argv[:6]} rc={r.returncode}\n{r.stdout[-1500:]}\n{r.stderr[-1500:]}")
    return r


# ---------------------------------------------------------------- backends

class Container:
    """podman (os4agent wrapper) or docker (validation only)."""

    def __init__(self, binary: list[str], mode: str, env=None):
        self.bin, self.mode, self.env = binary, mode, env

    def run(self, *args, check=True, env=None):
        return sh([*self.bin, *args], check=check, env=env or self.env)

    def start_source(self) -> str:
        name = f"mem-{self.mode}-src"
        self.run("rm", "-f", name, check=False)
        extra = []
        if self.mode == "criu":
            extra = ["--annotation", f"org.criu.config={REPO}/agents/agent-s/drivers/criu-baseline.conf", "--runtime", "/usr/sbin/runc"]
        self.run("run", "-d", "--name", name, "--security-opt", "seccomp=unconfined",
                 "--security-opt", "label=disable", "--shm-size=2g",
                 "--tmpfs", "/config:size=512m", "--tmpfs", "/tmp:size=1g", "--tmpfs", "/run:size=256m",
                 "-p", "3001", *extra, "--entrypoint", "bash", IMAGE, "-c", DESK)
        return name

    def exec(self, target: str, cmd: str, timeout=120):
        return sh([*self.bin, "exec", target, "bash", "-c", cmd], check=False, timeout=timeout, env=self.env)

    def fork(self, src: str, n: int) -> list[str]:
        base = f"mem-{self.mode}-c"
        if self.mode == "tfork":
            argv = [*self.bin, "--log-level=info", "container", "clone", "--live", f"--copies={n}",
                    "--tfork-overlay-btrfs", "--tfork-tcp-close", f"--tfork-ghost-limit={64 << 20}",
                    "--name", base, src]
            perf = os.environ.get("PERF_OUT")  # e.g. /mnt/btrfs/perf/fork.data: system-wide profile of the clone
            if perf:
                argv = ["perf", "record", "-a", "-g", "-F", "999", "-o", perf, "--", *argv]
            r = sh(argv, env=self.env)
            Path(os.environ.get("CLONE_LOG", "/tmp/tfork-clone.log")).write_text(r.stderr)
            return [l.strip() for l in r.stdout.splitlines() if len(l.strip()) == 64]
        # stock CRIU: stock runc + /usr/sbin/criu, one export, N restores (tcp-close via criu-baseline.conf)
        env = {**(self.env or os.environ), "OS4AGENT_CRIU_DIR": "/usr/sbin"}
        tar = Path("/mnt/ssd2/memcompare-criu.tar")
        try:
            self.run("container", "checkpoint", "--leave-running", "--tcp-established",
                     "--compress=none", f"--export={tar}", src, env=env)
            ids = []
            for i in range(n):
                r = self.run("container", "restore", f"--import={tar}", "--name", f"{base}-{i}",
                             "--ignore-static-ip", "--ignore-static-mac",
                             "--publish", "3001", env=env)
                ids.append(r.stdout.strip().splitlines()[-1])
            return ids
        finally:
            tar.unlink(missing_ok=True)

    def pids(self, targets: list[str]) -> list[int]:
        out = []
        for t in targets:
            pid = int(self.run("inspect", "--format", "{{.State.Pid}}", t).stdout.strip() or 0)
            out += pidns_members(pid) if pid else []
        return out

    def teardown(self, targets):
        if targets:
            self.run("rm", "-f", *targets, check=False)


class Aenv:
    def __init__(self):
        self.cli = os.environ.get("AENV") or str(Path(f"~{os.environ.get('SUDO_USER', '')}").expanduser() / ".local/bin/aenv")
        self.url = "http://127.0.0.1:8000"
        self.key = Path("/mnt/ssd2/aenv/env/secrets/api-key").read_text().strip()

    def a(self, *args, check=True, timeout=1800):
        return sh([self.cli, *args], check=check, timeout=timeout)

    def start_source(self) -> str:
        tmpl = [t for t in json.loads(self.a("template", "ls").stdout) if "webtop" in t["names"]]
        if not tmpl or tmpl[0]["buildStatus"] != "ready":
            if tmpl:
                self.a("template", "rm", "webtop")
            self.a("pull", IMAGE, "--name", "webtop", timeout=3600)
        out = self.a("start", "webtop", "--detach", "--timeout", "7200").stdout.split()
        sb = out[-1]
        self.exec(sb, bg(f"bash -c {shlex.quote(DESK)}"))
        return sb

    def exec(self, target, cmd, timeout=120):
        return sh([self.cli, "exec", target, "--", "bash", "-c", cmd], check=False, timeout=timeout)

    def fork(self, src, n):
        r = sh(["curl", "-fsS", "-X", "POST", "-H", f"X-API-Key: {self.key}",
                "-H", "Content-Type: application/json",
                "-d", json.dumps({"count": n, "timeout": 7200}), f"{self.url}/sandboxes/{src}/fork"])
        res = json.loads(r.stdout)
        errs = [e["error"] for e in res if "sandbox" not in e]
        if errs:
            raise RuntimeError(f"aenv fork errors: {errs}")
        return [e["sandbox"]["sandboxID"] for e in res]

    def pids(self, targets):
        # one firecracker VMM per sandbox; nothing else runs on this server during the test
        return [int(p) for p in os.listdir("/proc") if p.isdigit()
                and Path(f"/proc/{p}/comm").exists()
                and Path(f"/proc/{p}/comm").read_text().strip().startswith("firecracker")]

    def teardown(self, targets):
        for t in targets:
            self.a("rm", t, check=False)


# ---------------------------------------------------------------- experiment

def wait_ready(be, target, timeout=180):
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout:
        if be.exec(target, READY, timeout=10).returncode == 0:
            return time.monotonic() - t0
        time.sleep(1)
    log = be.exec(target, "tail -20 /tmp/wm.log /tmp/xvfb.log").stdout
    raise RuntimeError(f"desktop not ready on {target}:\n{log}")


def replay(be, target, steps, log):
    """Run steps; return seconds spent executing them (settle sleeps excluded)."""
    total = 0.0
    for desc, cmd, settle in steps:
        t0 = time.monotonic()
        r = be.exec(target, as_desktop(cmd))
        dt = time.monotonic() - t0
        total += dt
        log(f"    {target[:12]} {desc}: rc={r.returncode} {dt:.1f}s" + (f" {r.stderr.strip()[:200]}" if r.returncode else ""))
        time.sleep(settle)
    return total


def screenshot(be, target, path):
    grab = "python3 -c " + shlex.quote("from PIL import ImageGrab; ImageGrab.grab().save('/tmp/s.png')")
    r = be.exec(target, as_desktop(grab) + "; base64 -w0 /tmp/s.png")
    if r.returncode == 0 and r.stdout:
        import base64
        Path(path).write_bytes(base64.b64decode(r.stdout.strip().splitlines()[-1]))


def run_system(name, be, n, outdir, log):
    res = {"system": name, "n": n}
    if os.geteuid() == 0:
        subprocess.run(["sh", "-c", "sync; echo 3 > /proc/sys/vm/drop_caches"])
    avail0 = meminfo()["MemAvailable"] // 1024
    src = be.start_source()
    targets = [src]
    try:
        res["boot_s"] = round(wait_ready(be, src), 1)
        log(f"  [{name}] desktop up on {src[:12]} in {res['boot_s']}s; prefix trajectory")
        time.sleep(5)
        res["prefix_exec_s"] = round(replay(be, src, PREFIX, log), 1)
        screenshot(be, src, outdir / f"{name}-src.png")
        res["after_prefix"] = smaps(be.pids([src]))
        log(f"  [{name}] after prefix: {res['after_prefix']}")

        t0 = time.monotonic()
        kids = be.fork(src, n)
        res["fork_s"] = round(time.monotonic() - t0, 2)
        targets += kids
        log(f"  [{name}] forked {len(kids)} in {res['fork_s']}s")
        time.sleep(10)
        res["after_fork"] = smaps(be.pids(targets))
        log(f"  [{name}] after fork: {res['after_fork']}")

        res["branch_exec_s"] = [round(replay(be, k, branch_steps(i), log), 1) for i, k in enumerate(kids)]
        time.sleep(10)
        res["after_branch"] = smaps(be.pids(targets))
        log(f"  [{name}] after branch: {res['after_branch']}")
        for i, k in enumerate(kids[:2]):
            screenshot(be, k, outdir / f"{name}-child{i}.png")
        res["host_used_delta_mib"] = avail0 - meminfo()["MemAvailable"] // 1024
    except Exception as e:
        res["error"] = str(e)[-3000:]
        log(f"  [{name}] FAILED: {e}")
    finally:
        be.teardown(targets)
    return res


def table(results):
    hdr = (f"{'system':8} {'boot_s':>6} {'prefix_s':>8} {'fork_s':>7} {'branch_s':>8} | "
           f"{'PSS src':>8} {'PSS fork':>9} {'PSS branch':>10} | {'anon':>6} {'file':>6} {'shmem':>6} | {'x src':>6}")
    rows = [hdr, "-" * len(hdr)]
    for r in results:
        if "after_branch" not in r:
            rows.append(f"{r['system']:8} FAILED: {r.get('error', '')[:80]}")
            continue
        a, f, b = r["after_prefix"], r["after_fork"], r["after_branch"]
        g = lambda m: m / 1024
        br = sum(r["branch_exec_s"]) / len(r["branch_exec_s"])
        rows.append(f"{r['system']:8} {r['boot_s']:6.1f} {r['prefix_exec_s']:8.1f} {r['fork_s']:7.2f} {br:8.1f} | "
                    f"{g(a['pss_mib']):8.2f} {g(f['pss_mib']):9.2f} {g(b['pss_mib']):10.2f} | "
                    f"{g(b['pss_anon_mib']):6.2f} {g(b['pss_file_mib']):6.2f} {g(b['pss_shmem_mib']):6.2f} | {b['pss_mib'] / a['pss_mib']:6.2f}")
    rows.append("Times in s (prefix/branch = step execution, settle sleeps excluded; branch = mean per child). "
                "PSS in GiB, summed over source + N children. anon/file/shmem = after branch. "
                "'x src' = after-branch total / source alone (N+1 = no sharing, 1.0 = full sharing).")
    return "\n".join(rows)


def set_io_uring(on: bool):
    """Flip kernel.io_uring_disabled; restart aenv-server when enabling so its ublk daemon starts."""
    Path("/proc/sys/kernel/io_uring_disabled").write_text("0" if on else "2")
    if on:
        subprocess.run(["docker", "restart", "aenv-server"], check=True, capture_output=True)
        for _ in range(120):
            if subprocess.run(["curl", "-fs", "http://127.0.0.1:8000/health"], capture_output=True).returncode == 0:
                return
            time.sleep(1)
        raise RuntimeError("aenv-server not healthy after restart")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="tfork,criu,aenv")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--out", default="/mnt/ssd2/memcompare")
    ap.add_argument("--validate-docker", action="store_true")
    args = ap.parse_args()
    outdir = Path(args.out) / time.strftime("%Y%m%d-%H%M%S")
    outdir.mkdir(parents=True, exist_ok=True)
    logf = open(outdir / "log.txt", "a")

    def log(msg):
        print(msg, flush=True)
        logf.write(msg + "\n")
        logf.flush()

    if args.validate_docker:
        be = Container(["docker"], "docker")
        src = be.start_source()
        try:
            log(f"desktop ready in {wait_ready(be, src):.1f}s")
            time.sleep(5)
            replay(be, src, PREFIX + branch_steps(0), log)
            replay(be, src, [("show calc", FOCUS_CALC, 1)], log)
            screenshot(be, src, outdir / "docker.png")
            log(be.exec(src, "ps -eo rss,comm --sort=-rss | head -15").stdout)
        finally:
            be.teardown([src])
        log(f"screenshot: {outdir / 'docker.png'}")
        return

    pod_env = {**os.environ, "CONTAINERS_STORAGE_CONF": os.environ.get("STORAGE_CONF", "/mnt/ssd2/podman/storage.conf")}
    pod = [str(REPO / "podman-tfork.sh")]
    results = []
    for s in args.systems.split(","):
        log(f"=== {s} (n={args.n})")
        # tfork/CRIU need io_uring off host-wide; AENV's ublk storage needs it on.
        set_io_uring(s == "aenv")
        be = Aenv() if s == "aenv" else Container(pod, s, env=pod_env)
        results.append(run_system(s, be, args.n, outdir, log))
        (outdir / "results.json").write_text(json.dumps(results, indent=2))
    set_io_uring(False)
    log("\n" + table(results))
    log(f"\nresults: {outdir}/results.json")


if __name__ == "__main__":
    main()
