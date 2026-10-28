"""OSWorld rollouts on forked desktops with memory profiling. Runs as root on the env host (06).

  sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 venv/bin/python osw_run.py --system tfork --result-dir traces/<run>

Per task group: start a source desktop -> OSWorld task setup -> fork N copies -> N rollouts in parallel -> OSWorld scoring.
Outputs in <result-dir>/: config.json, events.jsonl, mem.jsonl, <domain>/<task>__g<k>/ (chat.jsonl, traj.jsonl, result.txt,
timing.json, step_<n>.png), failed_clones/ (CRIU logs of failed tfork/CKPT clones).
"""
import argparse, contextlib, ctypes, glob, json, os, random, re, resource, shlex, shutil, socket, subprocess, sys, threading, time, traceback
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
OSW = HERE / "OSWorld"
CWD = Path(os.environ.get("PWD", HERE))  # the caller's directory; we chdir into OSWorld below
sys.path[:0] = [str(OSW), str(HERE)]
os.chdir(OSW)  # OSWorld resolves its cache dir relative to cwd
resource.setrlimit(resource.RLIMIT_NOFILE, (resource.getrlimit(resource.RLIMIT_NOFILE)[1],) * 2)  # AENV forwarders hold many fds

ap = argparse.ArgumentParser()
ap.add_argument("--system", required=True, choices=["tfork", "criu", "stock-criu", "aenv"],
                help="tfork: one live clone of N copies | criu: N serial full dump+restore clones (our CRIU) | "
                     "stock-criu: runc + distro CRIU checkpoint/restore | aenv: AgentENV microVM fork API")
ap.add_argument("--tasks", default=str(HERE / "grpo_batch32v2.json"))
ap.add_argument("--result-dir", required=True)
ap.add_argument("--limit", type=int, default=0, help="first N tasks only")
ap.add_argument("--rollouts", type=int, default=8)
ap.add_argument("--max-steps", type=int, default=15)
ap.add_argument("--parallel", type=int, default=1, help="task groups live at once (0 = all)")
ap.add_argument("--fork-concurrency", type=int, default=4, help="task groups forking at once")
ap.add_argument("--base-fork", type=int, default=0, help="fork one booted desktop into every task's source (two-level tree)")
ap.add_argument("--groups", type=int, default=0, help="run this many task groups, cycling through the batch (0 = one per task)")
ap.add_argument("--shuffle-seed", type=int, default=-1, help="shuffle the batch with this seed first (-1 = keep its order)")
ap.add_argument("--sync-groups", type=int, default=0, help="all groups fork, then all roll out, then all tear down together")
ap.add_argument("--setup-concurrency", type=int, default=0, help="task groups booting and setting up at once (0 = no limit)")
ap.add_argument("--mem-limit-gib", type=float, default=0, help="stop the run when host used memory passes this (0 = off)")
ap.add_argument("--obs-timeout", type=float, default=600,
                help="seconds to wait for a slow desktop before giving up: accessibility tree / screenshot (OSWorld: 3 x 60 s), "
         "AENV fork pairing, post-fork fix-ups, boot")
ap.add_argument("--release-copies", type=int, default=0,
                help="remove each rollout's copy as soon as its rollout is scored (default: when its whole group is done)")
# agent
ap.add_argument("--model", default=os.environ.get("SERVED", "qwen3vl8b"))
ap.add_argument("--temperature", type=float, default=1.0)
ap.add_argument("--replay", default="", help="trace dir to replay instead of calling the model")
ap.add_argument("--replay-latency", type=float, default=1.0, help="replay: sleep this x the recorded model latency per step")
ap.add_argument("--spec", choices=["off", "tage"], default=os.environ.get("SPEC", "off"), help="shadow TAGE action predictor")
ap.add_argument("--spec-topk", type=int, default=8)
ap.add_argument("--spec-exec", type=int, default=0,
                help="speculative execution: fork each rollout's desktop K times per step and run TAGE's top-K guesses "
                     "while the model thinks; adopt the fork whose guess the model picks (turns on --spec tage)")
ap.add_argument("--prefix-cache", default="",
                help="dir of the prefix cache: hash(system, task, actions so far) -> checkpoint on disk, shared by epochs")
ap.add_argument("--prefix-depth", type=int, default=3, help="prefix cache: save checkpoints for prefixes up to this long")
# containers (tfork / criu / stock-criu)
ap.add_argument("--image", default="ghcr.io/wuklab/webtop:ubuntu-kde-osworld")
ap.add_argument("--os4agent", default="/mnt/ssd2/os4agent")
ap.add_argument("--storage-conf", default="/mnt/btrfs/podman/storage.conf")
ap.add_argument("--overlay-rootfs", type=int, default=1, help="tfork: --tfork-overlay-btrfs (copies share one page cache)")
ap.add_argument("--full-memcopy", type=int, default=1, help="criu: --tfork-full-memcopy (no CoW with the source)")
ap.add_argument("--save-ckpt", default="", help="criu: keep each group's CRIU image under this dir")
ap.add_argument("--net", choices=["auto", "slirp", "bridge"], default="auto", help="auto: slirp for stock-criu, else bridge")
ap.add_argument("--seccomp", default="auto", help="auto: seccomp_nopkey.json for stock-criu, else unconfined")
# aenv
ap.add_argument("--aenv-template", default="kde-osworld")
USER_HOME = os.path.expanduser(f"~{os.environ.get('SUDO_USER', '')}")  # we run under sudo; the aenv CLI is the user's
ap.add_argument("--aenv-cli", default=f"{USER_HOME}/.local/bin/aenv")
ap.add_argument("--aenv-home", default=USER_HOME, help="HOME holding the aenv CLI credentials")
ap.add_argument("--aenv-key", default="/mnt/ssd2/aenv/env/secrets/api-key", help="aenv-server API key file")
ap.add_argument("--sample-s", type=float, default=2.0, help="memory sampling interval")
a = ap.parse_args()

from desktop_env import desktop_env as dem  # noqa: E402  (needs sys.path above)
from desktop_env.desktop_env import DesktopEnv  # noqa: E402
from a11y_owl_agent import A11yAgent, linearize, refind, to_code  # noqa: E402
from toolspec.online import OnlineTage  # noqa: E402
from toolspec.keys import action_key  # noqa: E402
from spec_exec import ActionBook, PrefixCache  # noqa: E402

OUT = (CWD / a.result_dir).resolve()
OUT.mkdir(parents=True, exist_ok=True)
REPLAY = (CWD / a.replay).resolve() if a.replay else None
RUN = OUT.name.replace("_", "-")[:40]
DESK = HERE / "desk_osw.sh"  # desktop start script, identical on every system
PORTS = ("5000", "9222", "8006", "8080")  # OSWorld server, Chrome CDP, VNC, VLC
SPEC = OnlineTage(max(a.spec_topk, a.spec_exec)) if a.spec == "tage" or a.spec_exec else None
BOOK = ActionBook() if a.spec_exec else None
PREFIX = PrefixCache(str((CWD / a.prefix_cache).resolve()), a.prefix_depth) if a.prefix_cache else None
LOCK, ENV_LOCK, SPEC_LOCK = threading.Lock(), threading.Lock(), threading.Lock()
FORK_SEM = threading.Semaphore(a.fork_concurrency)
SETUP_SEM = threading.Semaphore(a.setup_concurrency) if a.setup_concurrency else contextlib.nullcontext()
ABORT = threading.Event()  # set by the sampler when host memory passes --mem-limit-gib
FORKED = DONE = None       # --sync-groups: Gates every group passes after its fork and after its rollouts
MEM = None
AENV_CGROUP_PID = None  # aenv-server's pid: every Firecracker VM is charged to that container's cgroup
BASES = []  # --base-fork: (name, addr, pid) per task index


# ---------------------------------------------------------------- helpers

def append_jsonl(path, rec):
    with LOCK, open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def log(event, **kw):
    rec = {"t": time.time(), "event": event, **kw}
    print(json.dumps(rec)[:400], flush=True)
    append_jsonl(OUT / "events.jsonl", rec)


def sh(argv, check=True, timeout=900, **kw):
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **kw)
    if check and r.returncode:
        out = (r.stderr or r.stdout).replace("\\n", "\n")
        errs = "\n".join(l.strip()[:300] for l in out.splitlines() if "Error (" in l)[:4000]
        raise RuntimeError(f"{' '.join(argv[:6])}... rc={r.returncode}: {errs or out[-1500:]}")
    return r


def setns_net(pid):
    """Move the calling thread into pid's network namespace."""
    with open(f"/proc/{pid}/ns/net") as f:
        if ctypes.CDLL(None, use_errno=True).setns(f.fileno(), 0x40000000):
            raise OSError(ctypes.get_errno(), "setns")


def check_abort():
    if ABORT.is_set():
        raise RuntimeError("memory limit reached")


class Gate:
    """Holds every group until all n have arrived and the last one has run on_last, or the run is aborted."""

    def __init__(self, n):
        self.n, self.k, self.open, self.cond = n, 0, False, threading.Condition()

    def arrive(self, on_last=lambda: None):
        with self.cond:
            self.k += 1
            last = self.k == self.n
        if last:
            on_last()  # nobody is released before this finishes
            with self.cond:
                self.open = True
                self.cond.notify_all()

    def wait(self):
        with self.cond:
            while not self.open and not ABORT.is_set():
                self.cond.wait(1)


def call_with_timeout(fn, timeout=None, netns=None):
    """Run fn() in its own thread, optionally inside pid netns's network namespace; re-raise its error."""
    box = {}

    def run():
        try:
            if netns:
                setns_net(netns)
            box["r"] = fn()
        except Exception as e:
            box["e"] = e
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(timeout)
    if th.is_alive():
        raise TimeoutError(f"timed out after {timeout}s")
    if "e" in box:
        raise box["e"]
    return box["r"]


# ---------------------------------------------------------------- memory

CG_KEYS = ("anon", "file", "shmem", "kernel", "inactive_file")
TOTAL_KEYS = ("pss_mib", "pss_anon_mib", "pss_file_mib", "pss_shmem_mib", "rss_mib", "cg_mib", "cg_ws_mib",
              *(f"cg_{k}_mib" for k in CG_KEYS))


def meminfo():
    return {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}


def pids_by_pidns():
    out = {}
    for p in filter(str.isdigit, os.listdir("/proc")):
        try:
            out.setdefault(os.readlink(f"/proc/{p}/ns/pid"), []).append(int(p))
        except OSError:
            pass
    return out


def smaps(pids):
    tot, n = dict.fromkeys(("Rss", "Pss", "Pss_Anon", "Pss_File", "Pss_Shmem"), 0), 0
    for pid in pids:
        try:
            for line in open(f"/proc/{pid}/smaps_rollup"):
                k, _, v = line.partition(":")
                if k in tot:
                    tot[k] += int(v.split()[0])
            n += 1
        except (OSError, ValueError):
            pass
    return {**{f"{k.lower()}_mib": round(v / 1024, 1) for k, v in tot.items()}, "nprocs": n}


def cgroup_mem(pid):
    """The container cgroup's own charge (includes tmpfs, unmapped page cache, kernel memory). Shared pages are charged
    once, to the cgroup that first touched them, so sums over containers don't double count. cg_ws is the working set
    (memory.current - inactive_file, as kubelet / cAdvisor define it): the charge minus page cache that can be dropped."""
    d = "/sys/fs/cgroup" + open(f"/proc/{pid}/cgroup").read().strip().split("::", 1)[1]
    stat = {l.split()[0]: int(l.split()[1]) for l in open(f"{d}/memory.stat")}
    current = int(open(f"{d}/memory.current").read())
    return {"cg_mib": round(current / 2**20, 1), "cg_ws_mib": round((current - stat.get("inactive_file", 0)) / 2**20, 1),
            **{f"cg_{k}_mib": round(stat.get(k, 0) / 2**20, 1) for k in CG_KEYS}}


class Mem:
    """Tracks live environments (name -> init pid, or ("vm", vmm pid) for AENV) and samples them into mem.jsonl."""

    def __init__(self):
        self.pid, self.owner, self.phase = {}, {}, {}  # name -> pid, name -> group, group -> phase
        self.cpu0 = self._cpu()
        m = meminfo()
        self.base_used = (m["MemTotal"] - m["MemAvailable"]) // 1024
        threading.Thread(target=self._loop, daemon=True).start()

    @staticmethod
    def _cpu():
        # user, nice, system, idle, iowait, irq, softirq, steal, guest, guest_nice: guest time is already inside user,
        # so the total is the first 8 fields (summing all 10 counted VM time twice and understated busy CPU under AENV)
        v = list(map(int, open("/proc/stat").readline().split()[1:]))
        return v[0] + v[1], v[2] + v[5] + v[6], v[4], sum(v[:8]), v[8] + v[9]

    def add(self, name, pid, group):
        self.pid[name], self.owner[name] = pid, group

    def drop(self, name):
        self.pid.pop(name, None)
        self.owner.pop(name, None)

    def snapshot(self, group=None):
        ns, m, per = pids_by_pidns(), meminfo(), {}
        for name, pid in list(self.pid.items()):
            if group is not None and self.owner.get(name) != group:
                continue
            try:
                if isinstance(pid, tuple):  # AENV: the VMM process holds the guest RAM
                    per[name] = smaps([pid[1]])
                else:
                    per[name] = {**smaps(ns.get(os.readlink(f"/proc/{pid}/ns/pid"), [])), **cgroup_mem(pid)}
                per[name]["t"] = self.owner.get(name)
            except OSError:
                pass
        used = (m["MemTotal"] - m["MemAvailable"]) // 1024
        host = {"used_mib": used, "avail_mib": m["MemAvailable"] // 1024, "used_delta_mib": used - self.base_used,
                "anon_mib": m["AnonPages"] // 1024, "shmem_mib": m["Shmem"] // 1024, "cached_mib": m["Cached"] // 1024}
        total = {k: round(sum(c.get(k, 0) for c in per.values()), 1) for k in TOTAL_KEYS}
        if AENV_CGROUP_PID and group is None:  # AENV: the cgroup numbers are the one cgroup holding all VMs
            try:
                total.update({k: v for k, v in cgroup_mem(AENV_CGROUP_PID).items()})
            except OSError:
                pass
        return {"containers": per, "total": total, "host": host}

    def _loop(self):
        while True:
            time.sleep(a.sample_s)
            try:
                c = self._cpu()
                d = [x - y for x, y in zip(c, self.cpu0)]
                self.cpu0, t = c, d[3] or 1
                rec = {"t": time.time(), "phases": dict(self.phase), "load1": os.getloadavg()[0],
                       "cpu": {"user": round(d[0] / t, 4), "sys": round(d[1] / t, 4), "iowait": round(d[2] / t, 4),
                               "guest": round(d[4] / t, 4)},
                       **self.snapshot()}
                append_jsonl(OUT / "mem.jsonl", rec)
                if a.mem_limit_gib and rec["host"]["used_mib"] > a.mem_limit_gib * 1024 and not ABORT.is_set():
                    ABORT.set()
                    log("mem_limit", used_gib=round(rec["host"]["used_mib"] / 1024, 1), envs=len(self.pid), total=rec["total"])
            except Exception as e:
                print("sampler:", e, flush=True)


# ---------------------------------------------------------------- containers: tfork / criu / stock-criu

def container_ids(stdout):
    return [l.strip() for l in stdout.splitlines() if len(l.strip()) == 64]


def keep_failed_clone(stderr):
    """Save a failed clone's CRIU logs to failed_clones/, delete its bundle, return the error lines."""
    m = re.search(r"(/[^\s\"]*/tfork-bundles/[0-9a-f]+)/crun-tfork\.log", stderr or "")
    if not m or not os.path.exists(m.group(1) + "/crun-tfork.log"):
        return (stderr or "")[-300:]
    b = m.group(1)
    keep = OUT / "failed_clones" / os.path.basename(b)[:16]
    keep.mkdir(parents=True, exist_ok=True)
    errs = [l.strip()[:220] for l in open(b + "/crun-tfork.log", errors="replace") if "Error" in l]
    for f in [b + "/crun-tfork.log", *glob.glob(b + "/img/tfork*.log*")]:
        shutil.copy(f, keep)
        if "restore" in f:
            errs += [f"{os.path.basename(f)}: {l.strip()[:200]}" for l in open(f, errors="replace") if "Error" in l][:4]
    for mnt in sorted((l.split()[1] for l in open("/proc/mounts") if l.split()[1].startswith(b + "/")), reverse=True):
        subprocess.run(["umount", "-l", mnt], check=False)
    if os.path.isdir(b + "/snap-ro"):
        subprocess.run(["btrfs", "subvolume", "delete", b + "/snap-ro"], capture_output=True)
    subprocess.run(["rm", "-rf", b], check=False)
    return errs[:12]


class Podman:
    def __init__(self, system):
        self.system = system
        # fixed containers.conf: podman-tfork.sh would otherwise rewrite it on every call (races under parallel clones)
        self.env = {**os.environ, "CONTAINERS_STORAGE_CONF": a.storage_conf, "CONTAINERS_CONF": str(HERE / "containers-os4agent.conf")}
        if system == "stock-criu":
            self.env["OS4AGENT_CRIU_DIR"] = "/usr/sbin"
        self.bin = [str(Path(a.os4agent) / "podman-tfork.sh")]
        self.slirp = a.net == "slirp" or (a.net == "auto" and system == "stock-criu")
        self.seccomp = a.seccomp if a.seccomp != "auto" else (
            str(HERE / "seccomp_nopkey.json") if system == "stock-criu" else "unconfined")

    def p(self, *args, check=True, timeout=900, env=None):
        return sh([*self.bin, *args], check=check, timeout=timeout, env=env or self.env)

    def info(self, name):
        """-> ("host:server:cdp:vnc:vlc", init pid)"""
        r = json.loads(self.p("inspect", name).stdout)[0]
        if not self.slirp:
            return f"{r['NetworkSettings']['IPAddress']}:" + ":".join(PORTS), r["State"]["Pid"]
        ports = r["NetworkSettings"]["Ports"]
        return "127.0.0.1:" + ":".join(ports[f"{p}/tcp"][0]["HostPort"] for p in PORTS), r["State"]["Pid"]

    def start_source(self, name):
        # cgroupns=host: restores otherwise fail in cgroupd; high nofile: Chromium's in-flight SCM_RIGHTS fds hit ETOOMANYREFS
        extra = ["--cgroupns=host", "--ulimit", "nofile=1048576:1048576"]
        if self.system == "stock-criu":
            extra += ["--runtime", "/usr/sbin/runc",
                      "--annotation", f"org.criu.config={HERE}/criu-baseline.conf"]
        if self.slirp:
            extra += ["--network", "slirp4netns:port_handler=slirp4netns", *[x for p in PORTS for x in ("-p", p)]]
        self.p("rm", "-f", name, check=False)
        self.p("run", "-d", "--name", name, *extra, "--security-opt", f"seccomp={self.seccomp}", "--security-opt", "label=disable",
               "--shm-size=2g", "--tmpfs", "/config:size=4g", "--tmpfs", "/tmp:size=1g", "--tmpfs", "/run:size=256m",
               "--entrypoint", "bash", a.image, "-c", DESK.read_text())
        return name, *self.info(name)

    def _clone(self, src, name, flags, tag, **fields):
        """One `container clone --live` with up to 5 attempts (backoff 20/40/60/80 s). -> stdout"""
        for attempt in range(5):
            if attempt:
                time.sleep(20 * attempt)
            t0 = time.time()
            env = {**self.env, "PODMAN_TFORK_NO_REAP": "1"}  # keep failed bundles so their logs can be saved
            r = self.p("container", "clone", "--live", *flags, "--name", name, src, check=False, env=env)
            ok = r.returncode == 0
            log(tag, **fields, attempt=attempt, ok=ok, secs=round(time.time() - t0, 3), why="" if ok else keep_failed_clone(r.stderr))
            if ok:
                return r.stdout
        raise RuntimeError(f"{tag} failed 5x")

    def fork(self, src, n, task, on_copy=lambda *_: None, part=""):
        """-> [(name, addr, pid)]. part keeps clone names unique when one source is forked several times."""
        ghost = f"--tfork-ghost-limit={64 << 20}"
        if self.system in ("tfork", "criu"):
            self.p("exec", src, "true")  # let tini reap exec children before the freeze
            time.sleep(0.1)
        if self.system == "tfork":
            flags = [f"--copies={n}", "--persistent=async", "--tfork-tcp-close", ghost]
            if a.overlay_rootfs:
                flags.append("--tfork-overlay-btrfs")
            names = container_ids(self._clone(src, f"{src}-k{part}", flags, "tfork_clone", task=task))
        elif self.system == "criu":  # CKPT: N serial single-copy clones, each a full dump + restore
            flags = ["--copies=1", "--persistent=sync", "--tfork-tcp-close", ghost]
            if a.full_memcopy:
                flags.append("--tfork-full-memcopy")
            names = []
            for i in range(n):
                check_abort()
                names += container_ids(self._clone(src, f"{src}-k{part}{i}", flags, "ckpt_clone", task=task, copy=i))
                on_copy(names[-1], *self.info(names[-1]))
        else:
            names = self._checkpoint_restore(src, n, task)
        return [(nm, *self.info(nm)) for nm in names]

    def _checkpoint_restore(self, src, n, task):
        """stock-criu: one checkpoint --leave-running, then n restores."""
        tar = Path(a.storage_conf).parent / f"criu-{src}.tar"
        try:
            t0 = time.time()
            self.p("container", "checkpoint", "--leave-running", "--tcp-established", "--compress=none", f"--export={tar}", src)
            log("criu_checkpoint", task=task, secs=round(time.time() - t0, 3), image_mib=round(tar.stat().st_size / 2**20, 1))
            names = []
            for i in range(n):
                t1, name = time.time(), f"{src}-k-{i}"
                pub = [x for p in PORTS for x in ("--publish", p)] if self.slirp else []
                self.p("container", "restore", f"--import={tar}", "--name", name, "--ignore-static-ip", "--ignore-static-mac", *pub)
                log("criu_restore", task=task, copy=i, secs=round(time.time() - t1, 3))
                names.append(name)
            return names
        finally:
            tar.unlink(missing_ok=True)

    def run_in(self, name, cmd):
        return self.p("exec", name, "bash", "-c", cmd, check=False, timeout=a.obs_timeout)

    def save(self, name, path):
        """Checkpoint a running desktop to disk (--prefix-cache); it keeps running."""
        self.p("container", "checkpoint", "--leave-running", "--tcp-established", "--compress=none", f"--export={path}.tar",
               name, timeout=a.obs_timeout)
        return {"system": self.system, "path": f"{path}.tar"}

    def load(self, entry, name):
        """A new desktop restored from a save() checkpoint. -> (name, addr, pid)"""
        pub = [x for p in PORTS for x in ("--publish", p)] if self.slirp else []
        self.p("container", "restore", f"--import={entry['path']}", "--name", name, "--ignore-static-ip",
               "--ignore-static-mac", *pub, timeout=a.obs_timeout)
        return (name, *self.info(name))

    def save_checkpoint(self, clone, dest, task):
        """Reflink-copy a CKPT clone's CRIU image (its tfork bundle img/) to dest."""
        batch = json.loads(self.p("inspect", clone).stdout)[0]["Config"]["Annotations"]["io.podman.tfork.batch-id"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        sh(["cp", "-a", "--reflink=auto", f"{Path(a.storage_conf).parent}/storage/tfork-bundles/{batch}/img", str(dest)])
        log("checkpoint_saved", task=task, path=str(dest), mib=int(sh(["du", "-sm", str(dest)]).stdout.split()[0]),
            secs=round(time.time() - t0, 2))

    def rm(self, names):
        if names:  # -t 0: kill at once; the desktop ignores SIGTERM, so the default 10 s wait only delays freeing memory
            self.p("rm", "-f", "-t", "0", *names, check=False, timeout=300)


# ---------------------------------------------------------------- AENV (Firecracker microVMs)

class Forwarder:
    """127.0.0.1:<port> -> TCP relay to a VM port, connecting from inside aenv-server's network namespace.
    Bypasses AENV's HTTP proxy, which cuts any request at 30 s (the LibreOffice a11y tree exceeds that under load)."""

    def __init__(self, netns_pid, ip, port):
        self.ns, self.up = netns_pid, (ip, int(port))
        self.ls = socket.socket()
        self.ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ls.bind(("127.0.0.1", 0))
        self.ls.listen(256)
        self.local = self.ls.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                c, _ = self.ls.accept()
            except OSError:
                return
            threading.Thread(target=self._conn, args=(c,), daemon=True).start()

    def _conn(self, c):
        try:
            setns_net(self.ns)  # this thread only
            u = socket.create_connection(self.up)
        except OSError:
            c.close()
            return
        threading.Thread(target=self._pipe, args=(u, c), daemon=True).start()
        self._pipe(c, u)

    @staticmethod
    def _pipe(src, dst):
        try:
            while data := src.recv(65536):
                dst.sendall(data)
        except OSError:
            pass
        finally:
            for s in (src, dst):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def close(self):
        self.ls.close()


class Aenv:
    URL = "http://127.0.0.1:8000"

    def __init__(self):
        self.key = Path(a.aenv_key).read_text().strip()
        self.env = {**os.environ, "HOME": a.aenv_home}
        global AENV_CGROUP_PID
        self.srv = AENV_CGROUP_PID = int(sh(["docker", "inspect", "aenv-server", "--format", "{{.State.Pid}}"]).stdout)
        self.fw, self.pid, self.ip = {}, {}, {}  # sandbox -> forwarders / VMM pid / slot address
        self.owned, self.lock = set(), threading.Lock()

    def api(self, method, path, body=None, timeout=600):
        req = urllib.request.Request(self.URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-API-Key": self.key, "Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")

    def cli(self, *args, check=True, timeout=900):
        return sh([a.aenv_cli, *args], check=check, timeout=timeout, env=self.env)

    @staticmethod
    def active_vmms():
        """Firecracker processes serving a sandbox (they hold its /dev/ublkb* devices)."""
        out = set()
        for p in filter(str.isdigit, os.listdir("/proc")):
            try:
                if open(f"/proc/{p}/comm").read().startswith("firecracker") and any(
                        os.readlink(f"/proc/{p}/fd/{fd}").startswith("/dev/ublkb") for fd in os.listdir(f"/proc/{p}/fd")):
                    out.add(int(p))
            except OSError:
                pass
        return out

    def claim(self, before, n, timeout=None):
        """The n VMMs that became active since `before` (call under self.lock)."""
        t0, new, timeout = time.time(), [], timeout or a.obs_timeout
        while time.time() - t0 < timeout:
            new = sorted(self.active_vmms() - before - self.owned)
            if len(new) >= n:
                self.owned.update(new[:n])
                return new[:n]
            time.sleep(0.2)
        raise RuntimeError(f"expected {n} new firecracker VMMs, found {len(new)}")

    def slot_ip(self, vmm):
        """VMM pid -> its slot address: aenv-server routes it via the VMM netns' vpeer address."""
        vpeer = sh(["nsenter", "-t", str(vmm), "-n", "ip", "-4", "-o", "addr", "show", "dev", "vpeer"]).stdout.split()[3].split("/")[0]
        for line in sh(["nsenter", "-t", str(self.srv), "-n", "ip", "-4", "route"]).stdout.splitlines():
            f = line.split()
            if len(f) >= 3 and f[1:3] == ["via", vpeer]:
                return f[0]
        raise RuntimeError(f"no aenv route via {vpeer} (vmm {vmm})")

    def whoami(self, ip, timeout=30):
        """Read the sandbox id tag from a VM over the direct path."""
        body = json.dumps({"command": "cat /tmp/.aenv_sandbox_id", "shell": True}).encode()
        req = urllib.request.Request(f"http://{ip}:5000/execute", data=body, headers={"Content-Type": "application/json"})
        try:
            return call_with_timeout(lambda: json.loads(urllib.request.urlopen(req, timeout=timeout).read()).get("output", "").strip(),
                                     netns=self.srv)
        except Exception:
            return ""

    def info(self, sb):
        fws = self.fw.setdefault(sb, [Forwarder(self.srv, self.ip[sb], p) for p in PORTS])
        return "127.0.0.1:" + ":".join(str(f.local) for f in fws), ("vm", self.pid[sb])

    def start_source(self, name):
        with self.lock:
            before = self.active_vmms()
            sb = self.cli("start", a.aenv_template, "--detach", "--timeout", "7200").stdout.split()[-1]
            self.pid[sb] = self.claim(before, 1)[0]
        self.ip[sb] = self.slot_ip(self.pid[sb])
        self.cli("upload", sb, str(DESK), "/tmp/desk_osw.sh")
        self.cli("exec", sb, "--", "bash", "-c", "setsid nohup bash /tmp/desk_osw.sh >/dev/null 2>&1 < /dev/null &")
        return sb, *self.info(sb)

    def fork(self, src, n, task, on_copy=None, part=""):
        with self.lock:
            before, t0 = self.active_vmms(), time.time()
            res = self.api("POST", f"/sandboxes/{src}/fork", {"count": n, "timeout": 7200})
            if errs := [e.get("error") for e in res if "sandbox" not in e]:
                raise RuntimeError(f"aenv fork errors: {errs}")
            kids = [e["sandbox"]["sandboxID"] for e in res]
            vmms = self.claim(before, len(kids))
            fork_s = time.time() - t0
        t1 = time.time()
        self._pair(kids, vmms)
        log("aenv_fork", task=task, copies=len(kids), secs=round(fork_s, 3), pair_secs=round(time.time() - t1, 3))
        return [(k, *self.info(k)) for k in kids]

    def _pair(self, kids, vmms):
        """Match each forked sandbox to its VMM: tag it via AENV exec, read the tag back over each VM's direct address."""
        for k in kids:
            self.cli("exec", k, "--", "sh", "-c", f"echo {k} > /tmp/.aenv_sandbox_id", timeout=a.obs_timeout)
        deadline = time.time() + a.obs_timeout  # a just-forked VM on a busy host can take minutes to answer
        for vmm in vmms:
            ip = self.slot_ip(vmm)
            while (k := self.whoami(ip)) not in kids:
                if time.time() > deadline:
                    raise RuntimeError(f"aenv fork: VM {ip} answered {k!r} (empty = no answer), not one of this fork's copies, "
                                       f"within {a.obs_timeout:.0f}s")
                check_abort()
                time.sleep(10)
            self.pid[k], self.ip[k] = vmm, ip
        if len({self.ip.get(k) for k in kids}) != len(kids):
            raise RuntimeError("aenv fork: copies and VMs did not pair 1:1")

    def run_in(self, name, cmd):
        return self.cli("exec", name, "--", "bash", "-c", cmd, check=False, timeout=a.obs_timeout)

    def save(self, sb, path):
        """Persistent AENV snapshot of a running sandbox (--prefix-cache)."""
        snap = "pfx-" + os.path.basename(path)
        self.cli("snapshot", "create", sb, "--name", snap, timeout=a.obs_timeout)
        return {"system": "aenv", "snapshot": snap}

    def load(self, entry, _name):
        """A new sandbox started from a save() snapshot. -> (sandbox, addr, ("vm", pid))"""
        with self.lock:
            before = self.active_vmms()
            sb = self.cli("start", entry["snapshot"], "--detach", "--timeout", "7200").stdout.split()[-1]
            self.pid[sb] = self.claim(before, 1)[0]
        self.ip[sb] = self.slot_ip(self.pid[sb])
        return (sb, *self.info(sb))

    def rm(self, names):
        for n in names:
            for f in self.fw.pop(n, []):
                f.close()
            self.owned.discard(self.pid.pop(n, None))
            self.cli("rm", n, check=False, timeout=120)


def prepare_host(system):
    """AENV needs io_uring and its server; tfork/CRIU need io_uring disabled (and so the AENV server stopped)."""
    def aenv_up():
        try:
            return urllib.request.urlopen(Aenv.URL + "/health", timeout=3).status in (200, 204)
        except Exception:
            return False
    knob = "/proc/sys/kernel/io_uring_disabled"
    if system == "aenv":
        open(knob, "w").write("0\n")
        if not aenv_up():
            sh(["docker", "start", "aenv-server"])
            for _ in range(90):
                if aenv_up():
                    break
                time.sleep(2)
            else:
                raise SystemExit("aenv-server did not become healthy")
    else:
        if sh(["docker", "ps", "-q", "-f", "name=^aenv-server$"]).stdout.strip():
            sh(["docker", "stop", "aenv-server"], timeout=300)
        open(knob, "w").write("2\n")
    log("host_mode", system=system, io_uring_disabled=int(open(knob).read()), aenv_server=aenv_up())


# ---------------------------------------------------------------- OSWorld glue

class FixedProvider:
    """OSWorld provider for an already-running desktop at "host:server:cdp:vnc:vlc"."""

    def __init__(self, addr): self.addr = addr
    def start_emulator(self, *_a, **_k): pass
    def get_ip_address(self, *_a, **_k): return self.addr
    def stop_emulator(self, *_a, **_k): pass
    def revert_to_snapshot(self, *_a, **_k): raise RuntimeError("forked copies are never reverted")
    def save_state(self, *_a, **_k): pass


class FixedManager:
    def get_vm_path(self, *_a, **_k): return "external"


def make_env(addr):
    with ENV_LOCK:  # the provider factory is module-global
        dem.create_vm_manager_and_provider = lambda *_a, **_k: (FixedManager(), FixedProvider(addr))
        env = DesktopEnv(provider_name="docker", path_to_vm=f"external-{addr}", action_space="pyautogui",
                         require_a11y_tree=True, headless=True, recording_update="off")
    # One long wait instead of OSWorld's 3 x 60 s: a timed-out request keeps running in the desktop's server, so
    # retrying a slow (CPU-starved) desktop only stacks more tree builds on it.
    env.controller.request_timeout, env.controller.retry_times = a.obs_timeout, 1
    return env


def observe(env, obs=None):
    """An observation with an accessibility tree: refetch until it has one or --obs-timeout runs out."""
    t0 = time.time()
    while obs is None or obs.get("accessibility_tree") is None:
        if time.time() - t0 > a.obs_timeout:
            raise TimeoutError(f"no accessibility tree from the desktop in {a.obs_timeout:.0f}s")
        check_abort()
        obs = env._get_obs()
    return obs


def wait_ready(addr, timeout=None):
    timeout = timeout or max(240, a.obs_timeout)
    host, port = addr.split(":")[:2]
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if urllib.request.urlopen(f"http://{host}:{port}/screenshot", timeout=10).status == 200:
                return time.time() - t0
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError(f"desktop {addr} not ready in {timeout}s")


def evaluate(env, timeout=600):
    """OSWorld scoring with a time limit (some postconfigs hang on a LibreOffice dialog)."""
    return float(call_with_timeout(env.evaluate, timeout))


# Fork fixups, same on every system: copies get an empty /etc/hosts, and a Chrome task's CDP relay (socat) dies at the fork.
HOSTS_FIX = ("[ -s /etc/hosts ] || printf '127.0.0.1\\tlocalhost\\n::1\\tlocalhost ip6-localhost ip6-loopback\\n"
             "ff02::1\\tip6-allnodes\\nff02::2\\tip6-allrouters\\n' > /etc/hosts")


def relay_restart(task):
    for c in task.get("config", []):
        cmd = (c.get("parameters") or {}).get("command")
        cmd = " ".join(cmd) if isinstance(cmd, list) else str(cmd or "")
        if c.get("type") in ("launch", "command", "execute") and cmd.startswith("socat") and "tcp-listen:9222" in cmd:
            return f"pkill -xf {shlex.quote(cmd)}; setsid nohup {cmd} >/dev/null 2>&1 < /dev/null &"
    return None


def fixup_copies(sysm, kids, task=None):
    relay = relay_restart(task) if task else None
    for name, *_ in kids:
        sysm.run_in(name, HOSTS_FIX + (f"; {relay}" if relay else ""))


# ---------------------------------------------------------------- agents and rollouts

class ReplayAgent:
    """Replays a recorded rollout's chat.jsonl: each target is re-found by (role, name) in the current tree,
    else the recorded coordinates are used. Writes chat.jsonl like A11yAgent."""

    def __init__(self, src):
        self.steps = [json.loads(l) for l in open(src / "chat.jsonl")]
        self.n, self.log, self.last = 0, None, None
        self.stats = {"match": 0, "coords": 0, "no_target": 0}

    def reset(self, *_a, **_k): pass

    def predict(self, instruction, obs):
        st = self.steps[self.n] if self.n < len(self.steps) else {"action": {"action": "done"}, "rows": [], "code": "DONE"}
        self.n += 1
        act, rec_rows = dict(st["action"]), st["rows"]
        if a.replay_latency and st.get("t"):
            time.sleep(a.replay_latency * max(0.0, st["t"]["llm_end"] - st["t"]["llm_start"]))
        _, rows = linearize(obs["accessibility_tree"])
        how = "no_target"
        if keys := [k for k in ("id", "from", "to") if isinstance(act.get(k), int) and 0 <= act[k] < len(rec_rows)]:
            new = {k: refind(rec_rows[act[k]], rows) for k in keys}
            how = "match" if None not in new.values() else "coords"
            if how == "match":
                act.update(new)
        try:
            code = st["code"] if how == "coords" else to_code(act, rows)
        except Exception:
            code = st["code"]
        self.stats[how] += 1
        self.last = {"response": st.get("response", ""), "action": act, "code": code, "replay": how,
                     "rows": [[r, n, list(b)] for r, n, b in rows]}
        if self.log:
            append_jsonl(self.log, self.last)
        return st.get("response", ""), [code]


def save_eval_evidence(env, d):
    try:
        (d / "eval_timeout.png").write_bytes(env.controller.get_screenshot() or b"")
        wins = env.controller.execute_python_command(
            "import subprocess; print(subprocess.run(['wmctrl', '-l'], capture_output=True, text=True).stdout)")
        (d / "eval_timeout_windows.txt").write_text(str(wins.get("output")))
    except Exception:
        pass


def task_env(addr, task):
    env = make_env(addr)
    env._set_task_info(task)
    env.setup_controller.reset_cache_dir(env.cache_dir)
    return env


def adopt(sysm, kid, new, gi, task):
    """Rollout copy `kid` ([name, addr, pid], updated in place) becomes desktop `new`; the old one is freed."""
    old = kid[0]
    sysm.rm([old])
    MEM.drop(old)
    kid[:] = list(new)
    MEM.add(new[0], new[2], gi)
    return task_env(new[1], task)


class Speculation:
    """--spec-exec: while the model thinks, fork the rollout's desktop once per TAGE guess and run each guess."""

    def __init__(self, sysm, kid, task, guesses, rows, gi, part):
        self.sysm, self.task, self.gi, self.t0 = sysm, task, gi, time.time()
        self.plan = [(g, c) for g in guesses if (c := BOOK.code_for(g, rows))][:a.spec_exec]
        self.forks, self.results, self.err, self.fork_s = [], [], None, 0.0
        self.th = threading.Thread(target=self._run, args=(kid[0], part), daemon=True)
        if self.plan:
            self.th.start()

    def _run(self, src, part):
        try:
            self.forks = [list(f) for f in self.sysm.fork(src, len(self.plan), self.task["id"], part=part)]
            for nm, _, pid in self.forks:
                MEM.add(nm, pid, self.gi)
            fixup_copies(self.sysm, self.forks, self.task)
            self.fork_s = time.time() - self.t0

            def run_guess(i):
                env = task_env(self.forks[i][1], self.task)
                obs, _, done, _ = env.step(self.plan[i][1])
                return env, (obs if done else observe(env, obs)), done
            with ThreadPoolExecutor(len(self.forks)) as ex:
                self.results = list(ex.map(run_guess, range(len(self.forks))))
        except Exception as e:
            self.err = repr(e)[-300:]

    def finish(self, key):
        """-> (fork desktop, env, obs, done) of the fork that ran `key`, or None. Every other fork is freed."""
        if not self.plan:
            return None
        t_wait = time.time()
        self.th.join()
        idx = next((i for i, (g, _) in enumerate(self.plan) if g == key), None) if self.results else None
        losers = [f[0] for j, f in enumerate(self.forks) if j != idx]
        self.sysm.rm(losers)
        for nm in losers:
            MEM.drop(nm)
        log("spec_exec", task=self.task["id"], g=self.gi, guesses=len(self.plan), hit=idx, fork_s=round(self.fork_s, 2),
            total_s=round(time.time() - self.t0, 2), waited_s=round(time.time() - t_wait, 2), error=self.err)
        return (self.forks[idx], *self.results[idx]) if idx is not None else None


def prefix_restore(sysm, task, keys, kid, gi, n):
    """--prefix-cache hit: replace the rollout's desktop with the checkpoint saved after `keys`. -> (env, obs) or None"""
    entry = PREFIX.get(a.system, task["id"], keys)
    if not entry:
        return None
    t0 = time.time()
    try:
        new = sysm.load(entry, f"{kid[0][:24]}-p{n}")
        fixup_copies(sysm, [new], task)
        env = adopt(sysm, kid, new, gi, task)
        obs = observe(env)
    except Exception as e:
        log("prefix_restore_failed", task=task["id"], g=gi, step=n, error=repr(e)[-300:])
        return None
    log("prefix_hit", task=task["id"], g=gi, step=n, secs=round(time.time() - t0, 2))
    return env, obs


def prefix_save(sysm, task, keys, kid, gi, n):
    """Save the rollout's desktop under `keys` unless the prefix is too deep, saved already, or being saved."""
    k = PREFIX.claim(a.system, task["id"], keys)
    if not k:
        return
    t0, entry = time.time(), None
    try:
        entry = sysm.save(kid[0], os.path.join(PREFIX.root, k))
        log("prefix_saved", task=task["id"], g=gi, step=n, secs=round(time.time() - t0, 2))
    except Exception as e:
        log("prefix_save_failed", task=task["id"], g=gi, step=n, error=repr(e)[-300:])
    finally:
        PREFIX.put(k, entry)


def rollout(task, domain, k, kid, d, sysm=None, gi=None):
    """kid: [name, addr, pid] of the rollout's desktop; speculation / the prefix cache may swap it (updated in place)."""
    d.mkdir(parents=True, exist_ok=True)
    tm = {"copy": kid[0], "t_start": time.time()}
    env = task_env(kid[1], task)
    hist, spec = [], None  # keys of the actions issued so far (the prefix); this step's pending speculation
    agent = ReplayAgent(REPLAY / domain / f"{task['id']}__g{k}") if REPLAY else A11yAgent(a.model, temperature=a.temperature)
    agent.reset()
    agent.log = str(d / "chat.jsonl")
    reward, steps, err = 0.0, 0, None
    try:
        obs = observe(env)
        for n in range(1, a.max_steps + 1):
            check_abort()
            guesses = []
            if SPEC:
                with SPEC_LOCK:
                    guesses = SPEC.decide(task["id"], str(d))["guesses"]
            if a.spec_exec and guesses:
                spec = Speculation(sysm, kid, task, guesses, linearize(obs["accessibility_tree"])[1], gi, f"s{k}x{n}-")
            _, codes = agent.predict(task["instruction"], obs)
            act, rows = agent.last["action"], agent.last["rows"]
            i = act.get("id", act.get("from"))
            hit = ({"role": rows[i][0], "name": rows[i][1], "key": f"{rows[i][0]}|{rows[i][1][:60]}"}
                   if isinstance(i, int) and 0 <= i < len(rows) else None)
            rec = {"step_num": n, "action_timestamp": time.strftime("%Y%m%d@%H%M%S") + f"{time.time() % 1:.6f}"[2:],
                   "action": json.dumps(act), "a11y_hit": hit, "code": codes[0]}
            if SPEC:
                with SPEC_LOCK:
                    if sp := SPEC.reveal(task["id"], str(d), act, hit):
                        rec["spec"] = sp
            key = action_key(act, hit)
            if BOOK:
                BOOK.remember(key, act, hit)
            t0 = time.time()
            took, spec = (spec.finish(key) if spec else None), None
            if took:  # a speculative fork already ran this action
                fork, env_new, obs, done = took
                old = kid[0]
                kid[:] = fork
                sysm.rm([old])
                MEM.drop(old)
                env, rec["skipped"] = env_new, "spec"
            elif PREFIX and key is not None and (hit_ := prefix_restore(sysm, task, hist + [key], kid, gi, n)):
                (env, obs), done, rec["skipped"] = hit_, False, "prefix"
            else:
                obs, _, done, _ = env.step(codes[0])
                if not done:
                    obs = observe(env, obs)
                    if PREFIX and key is not None:
                        prefix_save(sysm, task, hist + [key], kid, gi, n)
            if key is not None:
                hist.append(key)
            rec["exec_s"] = round(time.time() - t0, 3)
            if obs.get("screenshot"):
                (d / f"step_{n}.png").write_bytes(obs["screenshot"])
            append_jsonl(d / "traj.jsonl", rec)
            steps = n
            if done:
                break
        tm["t_eval"] = time.time()
        try:
            reward = evaluate(env)
        except TimeoutError:
            save_eval_evidence(env, d)
            raise
    except Exception as e:
        err = repr(e)
        traceback.print_exc()
    if spec:
        spec.finish(None)
    tm.update(t_end=time.time(), steps=steps, error=err, **({"replay": agent.stats} if REPLAY else {}))
    (d / "result.txt").write_text(f"{reward}\n")
    (d / "timing.json").write_text(json.dumps(tm, indent=1))
    log("rollout_done", task=task["id"], k=k, reward=reward, steps=steps, error=err, secs=round(tm["t_end"] - tm["t_start"], 1))
    return reward


# ---------------------------------------------------------------- task groups

def boot(sysm, name, owner, label):
    """Start a fresh desktop and wait until it is usable. -> (name, addr, pid)"""
    t0 = time.time()
    name, addr, pid = sysm.start_source(name)
    MEM.add(name, pid, owner)
    ready = wait_ready(addr)
    time.sleep(20)  # let the session settle (autostarts, a11y bus)
    log("boot", task=label, secs=round(time.time() - t0, 1), ready_s=round(ready, 1))
    return name, addr, pid


def group(sysm, gi, domain, tid, rep=0):
    task = json.load(open(OSW / f"evaluation_examples/examples/{domain}/{tid}.json"))
    src, kids, forked, released = f"osw-{RUN}-t{gi}", [], False, set()
    name = f"{tid}__r{rep}" if rep else tid  # repeats of a task (--groups > batch size) get their own dirs
    try:
        with SETUP_SEM:
            check_abort()
            MEM.phase[gi] = "boot"
            if BASES:
                src, addr, pid = BASES[gi]
                MEM.add(src, pid, gi)
            else:
                src, addr, pid = boot(sysm, src, gi, tid)

            MEM.phase[gi] = "setup"
            t0 = time.time()
            make_env(addr).reset(task_config=task)
            time.sleep(5)
            log("setup", task=tid, g=gi, secs=round(time.time() - t0, 1))
        log("mem_before_fork", task=tid, g=gi, **MEM.snapshot(gi))

        MEM.phase[gi] = "fork"
        with FORK_SEM:
            check_abort()
            t0 = time.time()
            kids = sysm.fork(src, a.rollouts, tid, on_copy=lambda nm, _ad, kp: MEM.add(nm, kp, gi))
            fork_s = round(time.time() - t0, 2)
        for nm, _, kp in kids:
            MEM.add(nm, kp, gi)
        fixup_copies(sysm, kids, task)
        if a.save_ckpt and a.system == "criu":
            sysm.save_checkpoint(kids[0][0], Path(a.save_ckpt) / OUT.name / domain / tid, tid)
        time.sleep(5)
        log("fork", task=tid, g=gi, system=a.system, copies=len(kids), secs=fork_s, **MEM.snapshot(gi))
        if FORKED:
            forked = True
            sync_point(FORKED, "all_forked")
            check_abort()

        MEM.phase[gi] = "rollouts"

        kids = [list(kid) for kid in kids]  # [name, addr, pid]; a rollout may swap its desktop

        def run(k, kid):
            reward = rollout(task, domain, k, kid, OUT / domain / f"{name}__g{k}", sysm, gi)
            if a.release_copies:  # free this copy now instead of when the whole group is done
                t0 = time.time()
                sysm.rm([kid[0]])
                MEM.drop(kid[0])
                released.add(kid[0])
                log("copy_released", task=tid, g=gi, k=k, secs=round(time.time() - t0, 2))
            return reward
        with ThreadPoolExecutor(len(kids)) as ex:
            rewards = list(ex.map(run, range(len(kids)), kids))
        log("group_done", task=tid, g=gi, rewards=rewards, mean=sum(rewards) / len(rewards), **MEM.snapshot(gi))
    except Exception as e:
        log("group_error", task=tid, g=gi, error=repr(e)[-1500:])
        traceback.print_exc()
    finally:
        if FORKED:  # a failed group still has to arrive, or the others would wait for it forever
            if not forked:
                FORKED.arrive(lambda: log("all_forked", **MEM.snapshot()))
            sync_point(DONE, "all_done")
        MEM.phase[gi] = "teardown"
        names = [src] + [nm for nm, *_ in kids if nm not in released]
        sysm.rm(names)
        for nm in names:
            MEM.drop(nm)
        MEM.phase.pop(gi, None)


def sync_point(gate, event):
    """Arrive at gate and wait for every group; the last one in logs a snapshot of the whole run before anyone moves on
    (at a few hundred desktops the snapshot takes ~20 s, and teardown must not start during it)."""
    gate.arrive(lambda: log(event, **MEM.snapshot()))
    gate.wait()


def base_fork(sysm, n):
    """Boot one desktop and fork it into n task sources; the base stays up until the end."""
    base, *_ = boot(sysm, f"osw-{RUN}-base", "base", "base")
    t0, kids = time.time(), []
    for i in range(0, n, 8):  # 8 copies per clone, the size tfork is tested at
        kids += sysm.fork(base, min(8, n - i), "base", part=f"{i // 8}-")
    fixup_copies(sysm, kids)
    for nm, addr, pid in kids:
        MEM.add(nm, pid, "base")  # re-owned by its group once that group starts
        wait_ready(addr)
    log("base_fork", copies=len(kids), secs=round(time.time() - t0, 2), **MEM.snapshot("base"))
    BASES.extend(kids)
    return base


def main():
    global MEM
    global FORKED, DONE
    batch = json.load(open(CWD / a.tasks))
    tasks = [(dom, t) for dom, ids in batch.items() for t in ids][:a.limit or None]
    if a.shuffle_seed >= 0:
        random.Random(a.shuffle_seed).shuffle(tasks)
    n = a.groups or len(tasks)
    todo = [(*tasks[i % len(tasks)], i // len(tasks)) for i in range(n)]  # (domain, task, repeat)
    if a.sync_groups and a.release_copies:
        raise SystemExit("--release-copies frees copies as rollouts end; --sync-groups holds them all until the end. Pick one.")
    if a.sync_groups:
        FORKED, DONE = Gate(n), Gate(n)
    (OUT / "config.json").write_text(json.dumps(vars(a), indent=1))
    prepare_host(a.system)
    MEM = Mem()
    sysm = Aenv() if a.system == "aenv" else Podman(a.system)
    log("run_start", system=a.system, spec=a.spec, tasks=len(todo), rollouts=a.rollouts, host_baseline=MEM.snapshot()["host"])
    base = base_fork(sysm, len(todo)) if a.base_fork else None
    try:
        with ThreadPoolExecutor(len(todo) if a.sync_groups else a.parallel or len(todo)) as ex:
            list(ex.map(lambda x: group(sysm, x[0], *x[1]), enumerate(todo)))
    finally:
        if base:
            sysm.rm([base])
            MEM.drop(base)
    if SPEC:
        (OUT / "spec_summary.json").write_text(json.dumps(SPEC.summary(), indent=1))
    log("run_done", aborted=ABORT.is_set())


if __name__ == "__main__":
    main()
