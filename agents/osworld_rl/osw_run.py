"""OSWorld rollouts on forked desktops with memory profiling. Runs as root on the env host (06).

  sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 venv/bin/python osw_run.py --system tfork --result-dir traces/<run>

Per task group: start a source desktop -> OSWorld task setup -> fork N copies -> N rollouts in parallel -> OSWorld scoring.
Outputs in <result-dir>/: config.json, events.jsonl, mem.jsonl, <domain>/<task>__g<k>/ (chat.jsonl, traj.jsonl, result.txt,
timing.json, step_<n>.png), failed_clones/ (CRIU logs of failed tfork/CKPT clones).
"""
import argparse, contextlib, ctypes, glob, json, os, random, re, resource, shlex, shutil, socket, stat, subprocess, sys, threading, time, traceback
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
ap.add_argument("--order-by", nargs="*", default=[],
                help="result dirs of earlier runs (e.g. the previous epoch): start the task groups whose slowest rollout "
                     "took longest there first, so the long ones get --parallel slots early; tasks not in them first")
ap.add_argument("--clone-copies-limit", type=int, default=0,
                help="copies being cloned at once over every clone (group forks, prefix saves, materializations; a clone "
                     "counts its --copies), first come first served; 0 = no limit. Many restores at once time out in CRIU")
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
ap.add_argument("--prefix-keep-since", type=float, default=0,
                help="prefix cache: at start, drop entries neither saved nor restored since this time (osw_loop.py: the "
                     "previous epoch's start, so each epoch keeps what the last one touched); 0 = keep all")
ap.add_argument("--prefix-min-free-gb", type=float, default=80,
                help="prefix cache: don't save when the podman store's disk has less free space than this")
ap.add_argument("--epoch", type=int, default=-1, help="the GRPO epoch this run is (osw_loop.py), recorded with cache entries")
ap.add_argument("--prefix-mem", action="store_true",
                help="prefix cache in memory (tfork): an entry is an idle copy -- one more copy in the group fork for the state "
                     "after setup, a 1-copy fork of the rollout's desktop after an action -- and a hit forks it again")
ap.add_argument("--prefix-mem-budget-gib", type=float, default=40, help="--prefix-mem: the snapshots' PSS is kept under this")
ap.add_argument("--prefix-policy", choices=["lru", "lfu", "gdsf"], default="lru",
                help="--prefix-mem: which snapshots go first. gdsf: the cheapest to lose (its step's desktop time x "
                     "(1 + hits)), aged by a clock that rises with each eviction")
ap.add_argument("--prefix-lazy", action="store_true",
                help="prefix cache: a hit returns the observation saved with the entry (the tool's reply) at once; the "
                     "rollout's desktop is forked from the deepest hit's snapshot only at the next miss or at the end")
ap.add_argument("--prefix-lazy-start", action="store_true",
                help="--prefix-lazy: a group whose state after setup is cached with its reply forks no copies; each "
                     "rollout starts on that reply and gets its desktop at its first miss (one fork per rollout)")
ap.add_argument("--prefix-tree", action="store_true",
                help="--prefix-mem: keep the cached prefixes a tree: save a prefix only if its parent is cached, evict "
                     "only leaves (by --prefix-policy), so a hit never follows an evicted ancestor")
ap.add_argument("--prefix-replies", action="store_true",
                help="--prefix-mem --prefix-lazy: keep the tool's reply (and the action's code) for every step up to "
                     "--prefix-depth, snapshots only at the root and where a rollout diverges; a miss forks the deepest "
                     "snapshot on the rollout's path and re-runs the actions below it without observing them, then "
                     "observes once and checks that against the saved reply")
ap.add_argument("--rerun-pause", type=float, default=2.0, help="--prefix-replies: wait after each re-run action "
                "(as OSWorld's step pause)")
ap.add_argument("--prefix-admit-cost", type=float, default=0,
                help="prefix cache: save a prefix only if (rollouts that reached its parent - 1) x the desktop time "
                     "of the steps from the state after setup to it >= this many seconds (~ a save's cost): where "
                     "trajectories repeat; a cheap step under expensive ones still counts their cost; 0 = off")
ap.add_argument("--prefix-admit-visits", type=int, default=0,
                help="prefix cache: save a prefix only if at least this many rollouts reached its parent (counted across "
                     "epochs); 0 = save every prefix")
ap.add_argument("--spec-warm", nargs="*", default=[],
                help="result dirs (e.g. earlier epochs) whose traj.jsonl the predictor learns before the run, and whose "
                     "actions the spec-exec action book learns; otherwise both start empty in every run")
# containers (tfork / criu / stock-criu)
ap.add_argument("--image", default="ghcr.io/wuklab/webtop:ubuntu-kde-osworld")
ap.add_argument("--os4agent", default="/mnt/ssd2/os4agent")
ap.add_argument("--storage-conf", default="/mnt/btrfs/podman/storage.conf")
ap.add_argument("--overlay-rootfs", type=int, default=1, help="tfork: --tfork-overlay-btrfs (copies share one page cache)")
ap.add_argument("--ro-rootfs", type=int, default=0,
                help="tfork: --tfork-ro-rootfs, every copy's rootfs a read-only bind mount of one shared snapshot (no "
                     "per-copy snapshot or overlay; needs --overlay-rootfs 0)")
ap.add_argument("--rootfs-check", choices=["off", "log", "ro"], default="off",
                help="test whether rollout desktops write their root filesystem after the fork (tfork): log = with "
                     "--overlay-rootfs 1, log each desktop's overlay upper (every rootfs change) when it is removed; "
                     "ro = with --overlay-rootfs 0, make each desktop's btrfs rootfs subvolume read-only once it exists")
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
from spec_exec import ActionBook, PrefixCache, exact_key  # noqa: E402

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
# --overlay-rootfs with the in-memory cache: its live clones of a rollout's copy (saves) and of a snapshot (forks at a
# miss) are overlay clones of an overlay clone too -- an overlay mount can't be btrfs-snapshotted
# the rootfs flag of every tfork clone (forks, prefix saves and hits)
OVERLAY = (["--tfork-overlay-btrfs"] if a.overlay_rootfs else ["--tfork-ro-rootfs"] if a.ro_rootfs else []) \
    if a.system == "tfork" else []
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


class CopyLimit:
    """--clone-copies-limit: at most `limit` copies being cloned at once (a clone counts its copies), in arrival order;
    a clone larger than the limit runs alone. limit 0: no limit."""

    def __init__(self, limit):
        self.limit, self.busy, self.next, self.serving = limit, 0, 0, 0
        self.cv = threading.Condition()

    @contextlib.contextmanager
    def take(self, n):
        """-> seconds waited"""
        if not self.limit:
            yield 0.0
            return
        t0 = time.time()
        with self.cv:
            me, self.next = self.next, self.next + 1
            self.cv.wait_for(lambda: self.serving == me and (self.busy == 0 or self.busy + n <= self.limit))
            self.busy += n
            self.serving += 1
            self.cv.notify_all()
        try:
            yield time.time() - t0
        finally:
            with self.cv:
                self.busy -= n
                self.cv.notify_all()


CLONES = CopyLimit(a.clone_copies_limit)


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
    # A recursive overlay clone's snap-ro is a symlink to its parent's (shared by the parent's running copies): deleting
    # "it" as a subvolume would delete the parent's. Only a real snap-ro of this bundle is deleted; rm -rf drops a link.
    if os.path.isdir(b + "/snap-ro") and not os.path.islink(b + "/snap-ro"):
        subprocess.run(["btrfs", "subvolume", "delete", b + "/snap-ro"], capture_output=True)
    elif os.path.islink(b + "/snap-ro"):  # --tfork-ro-rootfs: drop this bundle's reference to the shared snapshot
        owner = os.path.dirname(os.path.realpath(b + "/snap-ro"))
        with contextlib.suppress(OSError):
            os.remove(f"{owner}/snap-ro.refs/{os.path.basename(b)}")
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

    _src_locks, _src_locks_guard = {}, threading.Lock()

    def _src_lock(self, src):
        """Clones of one source run one at a time: two at once (two rollouts hitting the same in-memory snapshot
        together) fail in CRIU's seize ("zombie <init> found while seizing") or its RPC ("File exists")."""
        with self._src_locks_guard:
            return self._src_locks.setdefault(src, threading.Lock())

    def _clone(self, src, name, flags, tag, **fields):
        """One `container clone --live` with up to 5 attempts (backoff 20/40/60/80 s). -> stdout"""
        with self._src_lock(src):
            return self._clone_locked(src, name, flags, tag, **fields)

    def _clone_locked(self, src, name, flags, tag, **fields):
        n = next((int(f.split("=", 1)[1]) for f in flags if f.startswith("--copies=")), 1)
        for attempt in range(5):
            if attempt:
                time.sleep(20 * attempt)
            with CLONES.take(n) as waited:  # --clone-copies-limit; released during the backoff
                t0 = time.time()
                env = {**self.env, "PODMAN_TFORK_NO_REAP": "1"}  # keep failed bundles so their logs can be saved
                r = self.p("container", "clone", "--live", *flags, "--name", name, src, check=False, env=env)
            ok = r.returncode == 0
            log(tag, **fields, attempt=attempt, ok=ok, secs=round(time.time() - t0, 3), wait_s=round(waited, 2),
                why="" if ok else keep_failed_clone(r.stderr))
            if ok:
                return r.stdout
            if "no such container" in r.stderr:  # the source is gone: retrying can't help
                raise RuntimeError(f"{tag}: source {src[:12]} is gone")
        raise RuntimeError(f"{tag} failed 5x")

    def fork(self, src, n, task, on_copy=lambda *_: None, part=""):
        """-> [(name, addr, pid)]. part keeps clone names unique when one source is forked several times."""
        ghost = f"--tfork-ghost-limit={64 << 20}"
        if self.system in ("tfork", "criu"):
            self.seed_etc(src)
            self.p("exec", src, "true")  # let tini reap exec children before the freeze
            time.sleep(0.1)
        if self.system == "tfork":
            flags = [f"--copies={n}", "--persistent=async", "--tfork-tcp-close", ghost]
            flags += OVERLAY
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
        out = [(nm, *self.info(nm)) for nm in names]
        for nm, _, pid in out:
            rootfs_mark(nm, pid)
        return out

    def seed_etc(self, src):
        """tfork leaves podman's bind mounts of /etc/resolv.conf and /etc/hosts out of the dump (tforkPodmanSkipMnts) and
        the image's files are empty, so a copy would have no DNS and no localhost. Write them once into the source's own
        rootfs, under the bind mounts, before it is forked: every copy, and every clone of a copy, inherits them and
        nothing has to write a copy's rootfs. Only into a podman-storage rootfs, only what differs."""
        try:
            mnt = Path(self.p("mount", src).stdout.strip())
        except Exception as e:  # not a podman-storage container (a clone): its rootfs came with the files
            log("etc_seeded", src=src, ok=False, err=repr(e)[:200])
            return
        try:
            want = {"resolv.conf": Path(f"/proc/{self.info(src)[1]}/root/etc/resolv.conf").read_text(), "hosts": HOSTS}
            written = []
            for f, text in want.items():
                path = mnt / "etc" / f
                if not path.exists() or path.read_text() != text:
                    path.write_text(text)
                    written.append(f)
            log("etc_seeded", src=src, ok=True, written=written)
        finally:
            self.p("unmount", src, check=False)

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
        """Save a running desktop to disk (--prefix-cache); it keeps running. tfork / criu: a persistent live clone,
        stopped once its dump is done (docs/TFORK_RESTORE.md: the image is the desktop at clone time; `podman container
        checkpoint` does not handle clones). stock-criu: a checkpoint tar."""
        if a.prefix_mem:  # an idle live copy, nothing on disk
            self.p("exec", name, "true")
            time.sleep(0.2)  # as fork(): let tini reap the exec child, or CRIU finds a zombie while seizing
            flags = ["--copies=1", "--tfork-tcp-close", f"--tfork-ghost-limit={64 << 20}", *OVERLAY]
            clone = container_ids(self._clone(name, f"pfx-{RUN[:20]}-{os.path.basename(path)[:12]}", flags, "prefix_clone"))[0]
            return {"system": self.system, "mem": clone, "pid": self.info(clone)[1]}
        if self.system in ("tfork", "criu"):
            self.p("exec", name, "true")  # let tini reap exec children before the freeze, as fork() does
            flags = ["--copies=1", "--persistent=async", "--tfork-tcp-close", f"--tfork-ghost-limit={64 << 20}"]
            clone = container_ids(self._clone(name, f"pfx-{RUN[:20]}-{os.path.basename(path)[:12]}", flags, "prefix_clone"))[0]
            t0 = time.time()
            while (st := self.p("inspect", clone, "--format", "{{.Tfork.DumpStatus}}").stdout.strip()) != "done":
                if st not in ("", "pending", "inflight") or time.time() - t0 > a.obs_timeout:
                    self.p("rm", "-f", "-t", "0", clone, check=False)
                    raise RuntimeError(f"prefix clone {clone[:12]}: dump status {st!r} after {time.time() - t0:.0f}s")
                time.sleep(1)
            self.p("stop", "-t", "0", clone)  # a stopped persistent clone keeps its bundle and image
            return {"system": self.system, "clone": clone}
        self.p("container", "checkpoint", "--leave-running", "--tcp-established", "--compress=none", f"--export={path}.tar",
               name, timeout=a.obs_timeout)
        return {"system": self.system, "path": f"{path}.tar"}

    _batches, _batches_guard = {}, threading.Lock()

    def load_shared(self, entry, name, wait=1.0):
        """load() of an in-memory snapshot, but rollouts that ask for the same snapshot within `wait` s share one
        `--copies=k` clone (a group's rollouts usually miss at the same step together; one clone each, behind the
        source's lock, the k-th waited for k clones). -> (name, addr, pid)"""
        src = entry["mem"]
        with self._batches_guard:
            b = self._batches.get(src)
            leader = b is None
            if leader:
                b = self._batches[src] = {"n": 0, "done": threading.Event(), "ids": None, "err": None}
            i = b["n"]
            b["n"] += 1
        if leader:
            time.sleep(wait)
            with self._batches_guard:  # later requests start the next batch
                del self._batches[src]
            try:
                self.p("exec", src, "true", check=False)
                time.sleep(0.2)  # let tini reap the exec child first (a zombie fails the clone's seize)
                flags = [f"--copies={b['n']}", "--tfork-tcp-close", f"--tfork-ghost-limit={64 << 20}", *OVERLAY]
                b["ids"] = container_ids(self._clone(src, name, flags, "prefix_hit_clone", copies=b["n"]))
                if len(b["ids"]) != b["n"]:
                    raise RuntimeError(f"clone of {src[:12]}: {len(b['ids'])} copies, wanted {b['n']}")
            except Exception as e:
                b["err"] = e
            finally:
                b["done"].set()
        else:
            b["done"].wait()
        if b["err"]:
            raise RuntimeError(f"shared clone of {src[:12]} failed: {b['err']!r}")
        new = b["ids"][i]
        addr, pid = self.info(new)
        rootfs_mark(new, pid)
        wait_ready(addr)
        return new, addr, pid

    def load(self, entry, name):
        """A new desktop restored from a save() entry. -> (name, addr, pid)"""
        if "mem" in entry:  # fork the idle snapshot; it stays for the next hit
            self.p("exec", entry["mem"], "true", check=False)
            time.sleep(0.2)  # let tini reap the exec child first (a zombie fails the clone's seize)
            flags = ["--copies=1", "--tfork-tcp-close", f"--tfork-ghost-limit={64 << 20}", *OVERLAY]
            new = container_ids(self._clone(entry["mem"], name, flags, "prefix_hit_clone"))[0]
            addr, pid = self.info(new)
            rootfs_mark(new, pid)
            wait_ready(addr)
            return new, addr, pid
        if "clone" in entry:  # each tfork-restore is an independent new container; the clone stays for the next one
            self.p("container", "tfork-restore", "--name", name, entry["clone"], timeout=a.obs_timeout)
            addr, pid = self.info(name)
            wait_ready(addr)
            return name, addr, pid
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
        for n in names:
            rootfs_report(n)
        if names:  # -t 0: kill at once; the desktop ignores SIGTERM, so the default 10 s wait only delays freeing memory
            self.p("rm", "-f", "-t", "0", *names, check=False, timeout=300)


# ---------------------------------------------------------------- --rootfs-check

ROOTFS = {}  # desktop -> its overlay upper dir (log mode)


def root_mount(pid):
    """-> (fs type, root within the fs, super options) of the root mount in pid's mount namespace"""
    for line in open(f"/proc/{pid}/mountinfo"):
        f = line.split()
        if f[4] == "/":
            i = f.index("-")
            return f[i + 1], f[3], f[i + 3]
    raise RuntimeError(f"no root mount for pid {pid}")


def rootfs_mark(name, pid):
    """--rootfs-check: remember the desktop's upper (log), or make its rootfs subvolume read-only (ro)."""
    if a.rootfs_check == "off":
        return
    try:
        fstype, root, opts = root_mount(pid)
        if a.rootfs_check == "log":
            up = next((o[len("upperdir="):] for o in opts.split(",") if o.startswith("upperdir=")), None)
            if fstype != "overlay" or not up:
                raise RuntimeError(f"root is {fstype}, not an overlay with an upper (--overlay-rootfs 1?)")
            ROOTFS[name] = up
            return
        if fstype != "btrfs" or "tfork-bundles/" not in root:
            raise RuntimeError(f"root is {fstype} {root}, not a tfork btrfs subvolume (--overlay-rootfs 0?)")
        sub = Path(a.storage_conf).parent / "storage/tfork-bundles" / root.split("tfork-bundles/", 1)[1]
        r = sh(["btrfs", "property", "set", "-ts", str(sub), "ro", "true"], check=False)
        log("rootfs_ro", name=name, subvol=str(sub), ok=r.returncode == 0, err=r.stderr.strip()[:200])
    except Exception as e:
        log("rootfs_ro" if a.rootfs_check == "ro" else "rootfs_upper", name=name, ok=False, err=repr(e)[:200])


def rootfs_report(name):
    """--rootfs-check log: every path in the desktop's upper (new or changed files, whiteouts = deletions, dirs)."""
    up = ROOTFS.pop(name, None)
    if not up:
        return
    paths, kinds = [], {"file": 0, "dir": 0, "whiteout": 0, "symlink": 0, "other": 0}
    for d, dirs, files in os.walk(up):
        for n in dirs + files:
            st_ = os.lstat(os.path.join(d, n))
            k = ("dir" if stat.S_ISDIR(st_.st_mode) else "file" if stat.S_ISREG(st_.st_mode) else
                 "whiteout" if stat.S_ISCHR(st_.st_mode) and st_.st_rdev == 0 else "symlink" if stat.S_ISLNK(st_.st_mode)
                 else "other")
            kinds[k] += 1
            paths.append(f"{k[0]} {os.path.relpath(os.path.join(d, n), up)}")
    log("rootfs_upper", name=name, ok=True, n=len(paths), **kinds, paths=sorted(paths)[:300])


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
HOSTS = "127.0.0.1\tlocalhost\n::1\tlocalhost ip6-localhost ip6-loopback\nff02::1\tip6-allnodes\nff02::2\tip6-allrouters\n"
HOSTS_FIX = f"[ -s /etc/hosts ] || printf {shlex.quote(HOSTS)} > /etc/hosts"  # tfork: Podman.seed_etc already put it there


def relay_restart(task):
    for c in task.get("config", []):
        cmd = (c.get("parameters") or {}).get("command")
        cmd = " ".join(cmd) if isinstance(cmd, list) else str(cmd or "")
        if c.get("type") in ("launch", "command", "execute") and cmd.startswith("socat") and "tcp-listen:9222" in cmd:
            return f"pkill -xf {shlex.quote(cmd)}; setsid nohup {cmd} >/dev/null 2>&1 < /dev/null &"
    return None


def fixup_copies(sysm, kids, task=None):
    # tfork: the relay survives the clone (test_chrome_relay.py: still listening, DevTools answers, also in a clone of
    # a copy) and must not be restarted: one started through `podman exec` is outside the desktop's process tree, and
    # CRIU can't seize it when the copy is cloned again (in-memory prefix snapshots, spec forks). Other systems: as before.
    relay = relay_restart(task) if task and getattr(sysm, "system", None) != "tfork" else None
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
        t0 = time.time()
        if a.replay_latency and st.get("t"):
            time.sleep(a.replay_latency * max(0.0, st["t"]["llm_end"] - st["t"]["llm_start"]))
        t = {"obs": t0, "llm_start": t0, "llm_end": time.time()}  # as A11yAgent's chat.jsonl
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
                     "rows": [[r, n, list(b)] for r, n, b in rows], "t": t}
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
    return timed(env)


def timed(env):
    """Time the desktop's parts of a step (traj.jsonl): act_s the action (a `python -c` with pyautogui in the desktop),
    shot_s the screenshot, a11y_s the accessibility tree; the rest of exec_s is OSWorld's 2 s pause and the cache."""
    c, env.parts = env.controller, {}
    for meth, part in (("execute_python_command", "act_s"), ("get_screenshot", "shot_s"), ("get_accessibility_tree", "a11y_s")):
        def wrap(*args, _f=getattr(c, meth), _p=part, **kw):
            t0 = time.time()
            try:
                return _f(*args, **kw)
            finally:
                env.parts[_p] = env.parts.get(_p, 0.0) + time.time() - t0
        setattr(c, meth, wrap)
    return env


def take_parts(env):
    """-> the parts timed since the last call, rounded; and reset them."""
    if env is None:
        return {}
    out, env.parts = {k: round(v, 3) for k, v in env.parts.items()}, {}
    return out


def adopt(sysm, kid, new, gi, task):
    """Rollout copy `kid` ([name, addr, pid], updated in place) becomes desktop `new`; the old one is freed.
    --prefix-lazy-start: a rollout that has no desktop yet has addr None."""
    old = kid[0]
    if kid[1] is not None:
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


SNAP_EST_MIB = 450  # a new in-memory snapshot's PSS once its lineage is gone (test_mem_snapshot.py: 385-448 MiB)
SIZES = {}  # --prefix-mem: each snapshot's PSS (MiB) as budget_guard last measured it (replaced whole, never mutated)
# roots (a task's state after setup) go last: losing one costs that task boot + setup and, in tree mode, every hit
ROOTS_LAST = a.prefix_replies or a.prefix_tree
EVICT_LOCK = threading.Lock()  # one eviction at a time: concurrent saves picked (and logged) the same victims


def known_sizes():
    """The snapshots' PSS as last measured; one saved since counts SNAP_EST_MIB. make_room() used to read every
    snapshot's smaps before each save: with ~170 snapshots that took seconds on the saving rollout's time."""
    sizes = SIZES
    with PREFIX.lock:
        keys = [k for k, e in PREFIX.index.items() if e and "mem" in e]
    return {k: sizes.get(k, SNAP_EST_MIB) for k in keys}


def snapshot_sizes():
    """--prefix-mem: PSS (MiB) of every snapshot in the cache; a snapshot whose container is gone counts 0."""
    ns, out = pids_by_pidns(), {}
    with PREFIX.lock:
        entries = [(k, e) for k, e in PREFIX.index.items() if e and "mem" in e]
    for k, e in entries:
        try:
            out[k] = smaps(ns.get(os.readlink(f"/proc/{e['pid']}/ns/pid"), []))["pss_mib"]
        except OSError:
            out[k] = 0.0
    return out


def drop_snapshots(sysm, keys, reason, sizes=None):
    """Remove these snapshots, except any a hit pinned since they were chosen; each leaves the index (a lookup then
    misses) before its container goes, so a hit never lands on a removed snapshot (lazy_hit pins before it looks)."""
    with PREFIX.lock:
        keys = [k for k in keys if k not in PREFIX.pinned]
        gone = [(k, PREFIX.index.get(k) or {}) for k in keys]
        state = lambda t: "done" if t in PREFIX.finished else "running" if t in PREFIX.running else "pending"
    if a.prefix_replies:  # the snapshot goes, the reply stays: a later miss re-runs from a shallower snapshot
        PREFIX.detach(keys)
    else:
        PREFIX.drop(keys)
    for k, e in gone:
        if "mem" in e:
            sysm.rm([e["mem"]])
            MEM.drop(e["mem"])
        if e.get("obs") and not a.prefix_replies:
            Path(e["obs"]).unlink(missing_ok=True)
        log("prefix_evict", reason=reason, policy=a.prefix_policy, key=k, task=e.get("task"), depth=e.get("depth"),
            hits=e.get("hits", 0), saved_epoch=e.get("epoch"), pss_mib=(sizes or {}).get(k),
            age_s=round(time.time() - e.get("saved_at", time.time()), 1), task_state=state(e.get("task")))


def make_room(sysm, done_only=False):
    """--prefix-mem: evict by --prefix-policy until one more snapshot fits the budget (sizes as last measured).
    done_only: take only snapshots of tasks whose group is done this run (a prefix save: it is next used in the next
    epoch, a pending group's snapshot later in this one). -> False if it can't."""
    with EVICT_LOCK:
        sizes = known_sizes()
        out = PREFIX.victims(sizes, SNAP_EST_MIB, a.prefix_mem_budget_gib * 1024, a.prefix_policy, a.prefix_tree,
                             roots_last=ROOTS_LAST, done_only=done_only)
        if out is None:
            return False
        if out:
            drop_snapshots(sysm, out, "budget", sizes)
        return True


def budget_guard(sysm, every=30):
    """--prefix-mem: a snapshot's PSS grows after it is saved (its lineage writes to shared pages, or goes away), so
    between saves too: every `every` s, evict by policy while the snapshots are over the budget."""
    while not ABORT.is_set():
        time.sleep(every)
        try:
            global SIZES
            SIZES = snapshot_sizes()  # measured outside the lock (seconds); evictions under it
            with EVICT_LOCK:
                sizes = known_sizes()
                out = PREFIX.victims(sizes, 0, a.prefix_mem_budget_gib * 1024, a.prefix_policy, a.prefix_tree,
                                     roots_last=ROOTS_LAST)
                if out:
                    drop_snapshots(sysm, out, "budget_growth", sizes)
        except Exception as e:
            log("budget_guard_error", error=repr(e)[-300:])


def register_snapshot(k, entry, task, keys, gi, n, t0, benefit_s, step_s=None):
    """benefit_s: desktop time to reach this state from the rollout's start; step_s: of its last step alone (what
    losing this snapshot costs a later rollout that reaches its parent; gdsf), the root: its setup."""
    entry = {**entry, "epoch": a.epoch, "task": task["id"], "depth": len(keys), "benefit_s": round(benefit_s, 2),
             "step_s": round(benefit_s if step_s is None else step_s, 2),
             "parent": PREFIX.key(a.system, task["id"], keys[:-1]) if keys else None}
    PREFIX.put(k, entry)
    if "mem" in entry:
        MEM.add(entry["mem"], entry["pid"], "cache")
    log("prefix_saved", task=task["id"], g=gi, step=n, secs=round(time.time() - t0, 2), epoch=a.epoch, key=k,
        depth=len(keys), parent=entry["parent"],
        **({"snapshots": len([e for e in PREFIX.index.values() if e and "mem" in e])} if "mem" in entry else {}))


def prefix_restore(sysm, task, keys, kid, gi, n):
    """--prefix-cache hit: replace the rollout's desktop with the checkpoint saved after `keys`. -> (env, obs) or None"""
    k = PREFIX.key(a.system, task["id"], keys)
    PREFIX.pin(k)  # an eviction must not remove the snapshot while it is being forked
    try:
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
    finally:
        PREFIX.unpin(k)
    PREFIX.touch(a.system, task["id"], keys, a.epoch)
    log("prefix_hit", task=task["id"], g=gi, step=n, secs=round(time.time() - t0, 2), saved_epoch=entry.get("epoch"),
        epoch=a.epoch)
    return env, obs


def prefix_save(sysm, task, keys, kid, gi, n, benefit_s=0.0, obs=None, step_s=None):
    """Save the rollout's desktop under `keys` unless the prefix is too deep, saved already, being saved, or refused
    (--prefix-tree: parent not cached; --prefix-admit-visits: parent reached by too few rollouts)."""
    k = PREFIX.claim(a.system, task["id"], keys)
    if not k:
        return
    # --prefix-tree: the parent is a leaf until this entry is registered; pinned (before the check), no eviction takes it
    pk = PREFIX.key(a.system, task["id"], keys[:-1]) if a.prefix_tree and keys else None
    if pk:
        PREFIX.pin(pk)
    try:
        _prefix_save(sysm, task, keys, kid, gi, n, benefit_s, obs, k, step_s)
    finally:
        if pk:
            PREFIX.unpin(pk)


def _prefix_save(sysm, task, keys, kid, gi, n, benefit_s, obs, k, step_s=None):
    if why := PREFIX.refuse(a.system, task["id"], keys, a.prefix_tree, a.prefix_admit_visits, benefit_s,
                            a.prefix_admit_cost):
        PREFIX.release(k)
        log("prefix_save_skipped", task=task["id"], g=gi, step=n, reason=why)
        return
    free = shutil.disk_usage(Path(a.storage_conf).parent).free / 2**30
    if not a.prefix_mem and free < a.prefix_min_free_gb:
        PREFIX.release(k)
        log("prefix_save_skipped", task=task["id"], g=gi, step=n, reason="disk", free_gb=round(free, 1))
        return
    if a.prefix_mem and not make_room(sysm, done_only=a.prefix_tree):
        PREFIX.release(k)  # (tree mode: no finished group's snapshot left to take)
        log("prefix_save_skipped", task=task["id"], g=gi, step=n, reason="no_room" if a.prefix_tree else "budget")
        return
    t0, entry = time.time(), None
    try:
        entry = sysm.save(kid[0], os.path.join(PREFIX.root, k))
        if obs is not None and obs.get("accessibility_tree") is not None:  # the tool's reply, for --prefix-lazy hits
            entry["obs"] = os.path.join(PREFIX.root, f"{k}.obs.json")
            with open(entry["obs"], "w") as f:
                json.dump({"accessibility_tree": obs["accessibility_tree"]}, f)
        # --prefix-tree: the parent may still be being saved (a sibling's save, queued for a clone slot): register after
        # it; if it never is, drop this one (no entry without its parent)
        if a.prefix_tree and keys and not PREFIX.wait_saved(PREFIX.key(a.system, task["id"], keys[:-1]), a.obs_timeout):
            sysm.rm([entry["mem"]])
            if entry.get("obs"):
                Path(entry["obs"]).unlink(missing_ok=True)
            entry = None
            log("prefix_save_skipped", task=task["id"], g=gi, step=n, reason="parent_not_saved")
            return
        register_snapshot(k, entry, task, keys, gi, n, t0, benefit_s, step_s)
        entry = None  # registered
    except Exception as e:
        log("prefix_save_failed", task=task["id"], g=gi, step=n, error=repr(e)[-300:])
    finally:
        PREFIX.release(k)


def lazy_hit(task, keys):
    """lazy_entry() with the entry pinned. Pinned before the lookup: an eviction between the lookup and the pin would
    leave the rollout on a removed snapshot (drop_snapshots skips pinned entries); unpinned again on a miss."""
    k = PREFIX.key(a.system, task["id"], keys)
    PREFIX.pin(k)
    e = lazy_entry(task, keys)
    if e is None:
        PREFIX.unpin(k)
    return e


def lazy_entry(task, keys):
    """--prefix-lazy: the cache entry for this prefix if it has a saved reply and a live snapshot, else None.
    --prefix-replies: a reply is enough (a miss re-runs from a shallower snapshot), if the task's root snapshot lives."""
    e = PREFIX.get(a.system, task["id"], keys)
    if not e or not e.get("obs") or not os.path.exists(e["obs"]):
        return None
    if a.prefix_replies:
        root = PREFIX.get(a.system, task["id"], [])
        return e if root and "mem" in root and os.path.exists(f"/proc/{root['pid']}") else None
    if "mem" in e and not os.path.exists(f"/proc/{e['pid']}"):
        return None
    return e


CLOCK = re.compile(r"^\d{1,2}:\d{2}( ?[AP]M)?$")  # the taskbar's clock and date differ between any two runs
DATE = re.compile(r"^(\d{1,2}/\d{1,2}/\d{2,4}|Today is \w+ \d{1,2}, \d{4})$")


def tree_rows(obs):
    """The accessibility tree as [(role, name, box)] with the clock's and date's text masked (as equiv_check.py)."""
    mask = lambda r, n: "<clock>" if r == "label" and CLOCK.match(n) else "<date>" if DATE.match(n) else n
    return [(r, mask(r, n), tuple(b)) for r, n, b in linearize(obs["accessibility_tree"])[1]]


def prefix_reply(task, keys, obs, code, gi, n):
    """--prefix-replies: keep this step's reply and the action's code (to re-run it) under `keys`; no snapshot."""
    if len(keys) > PREFIX.depth or obs is None or obs.get("accessibility_tree") is None:
        return
    k = PREFIX.key(a.system, task["id"], keys)
    if PREFIX.get(a.system, task["id"], keys):
        return
    path = os.path.join(PREFIX.root, f"{k}.obs.json")
    with open(path, "w") as f:
        json.dump({"accessibility_tree": obs["accessibility_tree"]}, f)
    if PREFIX.put_new(k, {"obs": path, "code": code, "epoch": a.epoch, "task": task["id"], "depth": len(keys),
                          "parent": PREFIX.key(a.system, task["id"], keys[:-1])}):
        log("prefix_reply", task=task["id"], g=gi, step=n, depth=len(keys))


def prefix_snapshot(sysm, task, keys, kid, gi, n):
    """--prefix-replies: the rollout's desktop is at `keys` (a prefix with a reply but no snapshot), either a branch
    point (another rollout went another way from here; called before this rollout's own action runs) or an end state
    two rollouts reached. Keep the desktop's state as that prefix's snapshot, so a later rollout forks it there
    without re-running."""
    k = PREFIX.claim(a.system, task["id"], keys, upgrade=True)
    if not k:
        return
    try:
        if not make_room(sysm):
            log("prefix_save_skipped", task=task["id"], g=gi, step=n, reason="budget")
            return
        t0 = time.time()
        snap = sysm.save(kid[0], os.path.join(PREFIX.root, k))
        if not PREFIX.attach(k, snap):  # its reply is gone: nothing to hang the snapshot on
            sysm.rm([snap["mem"]])
            return
        MEM.add(snap["mem"], snap["pid"], "cache")
        log("prefix_saved", task=task["id"], g=gi, step=n, secs=round(time.time() - t0, 2), epoch=a.epoch, key=k,
            depth=len(keys), divergence=True, snapshots=len([e for e in PREFIX.index.values() if e and "mem" in e]))
    except Exception as e:
        log("prefix_save_failed", task=task["id"], g=gi, step=n, error=repr(e)[-300:])
    finally:
        PREFIX.release(k)


def rerun(env, code):
    """--prefix-replies: re-run a recorded action without observing it: its code, then OSWorld's pause."""
    if code is None:
        raise RuntimeError("no recorded code to re-run")
    if code not in ("WAIT", "DONE", "FAIL"):
        env.controller.execute_python_command(code)
    time.sleep(a.rerun_pause)


def rerun_materialize(sysm, task, kid, gi, n, virtual, hist):
    """--prefix-replies: the rollout is at `virtual` (depth v, answered from saved replies; hist[:v] its actions).
    Fork the deepest live snapshot on its path (depth s; the root at least), re-run actions s+1..v without observing
    them, observe once and check that against the saved reply at v (the caller snapshots v if it is a branch
    point). -> env"""
    k, entry, v = virtual  # k stays pinned until this succeeds; on an error the rollout unpins it
    t0 = time.time()
    for s in range(v, -1, -1):
        ks = PREFIX.key(a.system, task["id"], hist[:s])
        PREFIX.pin(ks)  # before the check: an eviction can't take it in between
        es = PREFIX.get(a.system, task["id"], hist[:s])
        if es and "mem" in es and os.path.exists(f"/proc/{es['pid']}"):
            break
        PREFIX.unpin(ks)
    else:
        raise RuntimeError(f"no live snapshot on the path of {task['id']}, not even the root")
    try:
        new = sysm.load_shared(es, f"{kid[0][:24]}-m{n}")
        fixup_copies(sysm, [new], task)
        env = adopt(sysm, kid, new, gi, task)
    finally:
        PREFIX.unpin(ks)
    t1, check = time.time(), None
    for d in range(s + 1, v + 1):
        rerun(env, (PREFIX.get(a.system, task["id"], hist[:d]) or {}).get("code"))
    rerun_s = time.time() - t1
    if v > s:
        got, want = tree_rows(observe(env)), tree_rows(json.load(open(entry["obs"])))
        check = "same" if got == want else "names_differ" if [x[:2] for x in got] != [x[:2] for x in want] else "boxes_differ"
    parts = take_parts(env)  # the re-run's desktop time, logged here rather than as the next step's
    log("prefix_materialize", task=task["id"], g=gi, step=n, depth=v, snap_depth=s, rerun=v - s,
        rerun_s=round(rerun_s, 2), check=check, secs=round(time.time() - t0, 2), **parts)
    PREFIX.unpin(k)
    return env


def materialize(sysm, task, kid, gi, n, virtual):
    """--prefix-lazy: the rollout is at the state of `virtual`'s snapshot but its desktop is stale; fork the snapshot
    into its desktop. -> env"""
    k, entry, depth = virtual
    t0 = time.time()
    # rollouts that miss together share one clone of the snapshot; k stays pinned until this succeeds (on an error
    # the rollout unpins it: unpinning here too would take another rollout's pin)
    new = (sysm.load_shared if "mem" in entry else sysm.load)(entry, f"{kid[0][:24]}-m{n}")
    fixup_copies(sysm, [new], task)
    env = adopt(sysm, kid, new, gi, task)
    PREFIX.unpin(k)
    log("prefix_materialize", task=task["id"], g=gi, step=n, depth=depth, secs=round(time.time() - t0, 2))
    return env


def save_root_reply(task, obs):
    """--prefix-lazy: the first observation after setup is the reply of the task's after-setup snapshot, which lets
    later groups start without copies (--prefix-lazy-start). Written once, by the first rollout to observe."""
    k = PREFIX.key(a.system, task["id"], [])
    with PREFIX.lock:
        e = PREFIX.index.get(k)
        if not e or e.get("obs") or obs.get("accessibility_tree") is None:
            return
        path = os.path.join(PREFIX.root, f"{k}.obs.json")
        with open(path, "w") as f:
            json.dump({"accessibility_tree": obs["accessibility_tree"]}, f)
        e["obs"] = path
        PREFIX._write()


def rollout(task, domain, k, kid, d, sysm=None, gi=None, start=None):
    """kid: [name, addr, pid] of the rollout's desktop; speculation / the prefix cache may swap it (updated in place).
    start: --prefix-lazy-start, (key, entry) of the cached after-setup state: no desktop yet (kid's addr is None)."""
    d.mkdir(parents=True, exist_ok=True)
    tm = {"copy": kid[0], "t_start": time.time()}
    env = task_env(kid[1], task) if not start else None
    hist, spec, spent = [], None, []  # exact keys of the actions so far (the prefix); this step's speculation; exec_s so far
    # desktop time of each step on the path, a hit counting what its step cost when it was saved: path_s[:n] sums the
    # cost to reach step n's state from the state after setup (--prefix-admit-cost)
    path_s = []
    virtual = None  # --prefix-lazy: (key, entry, depth) of the deepest hit while the desktop lags behind it
    agent = ReplayAgent(REPLAY / domain / f"{task['id']}__g{k}") if REPLAY else A11yAgent(a.model, temperature=a.temperature)
    agent.reset()
    agent.log = str(d / "chat.jsonl")
    reward, steps, err = 0.0, 0, None
    if PREFIX:
        PREFIX.visit(a.system, task["id"], [])
    try:
        if start:  # on the cached reply after setup; materialize() forks the desktop at the first miss
            PREFIX.pin(start[0])
            virtual = (start[0], start[1], 0)
            obs = json.load(open(start[1]["obs"]))
        else:
            obs = observe(env)
            tm["obs0_parts"] = take_parts(env)
            if PREFIX and a.prefix_lazy and a.prefix_mem:
                save_root_reply(task, obs)
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
            pkey = exact_key(act) if key is not None else None
            # --prefix-replies: another rollout already went (or is going) another way from this state
            branch = bool(PREFIX and a.prefix_replies and pkey is not None and PREFIX.note_child(a.system, task["id"], hist + [pkey]))
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
            elif PREFIX and a.prefix_lazy and pkey is not None and (e_ := lazy_hit(task, hist + [pkey])):
                k_ = PREFIX.key(a.system, task["id"], hist + [pkey])  # a hit (pinned): the saved reply, no desktop work
                if virtual:
                    PREFIX.unpin(virtual[0])
                virtual = (k_, e_, len(hist) + 1)
                obs = json.load(open(e_["obs"]))
                hit_s = e_.get("step_s") or 0.0
                done, rec["skipped"], rec["lazy"] = False, "prefix", True
                PREFIX.touch(a.system, task["id"], hist + [pkey], a.epoch)
                log("prefix_hit", task=task["id"], g=gi, step=n, secs=round(time.time() - t0, 3), lazy=True,
                    saved_epoch=e_.get("epoch"), epoch=a.epoch)
            elif not a.prefix_lazy and PREFIX and pkey is not None and (hit_ := prefix_restore(sysm, task, hist + [pkey], kid, gi, n)):
                (env, obs), done, rec["skipped"] = hit_, False, "prefix"
            else:
                if virtual:  # a miss after hits: bring the desktop to the deepest hit, then run the action there
                    env, virtual = (rerun_materialize(sysm, task, kid, gi, n, virtual, hist) if a.prefix_replies
                                    else materialize(sysm, task, kid, gi, n, virtual)), None
                if branch:  # the desktop is at the branch point now, before this rollout's own action: keep it
                    prefix_snapshot(sysm, task, hist, kid, gi, n)
                obs, _, done, _ = env.step(codes[0])
                if not done:
                    obs = observe(env, obs)
                    if PREFIX and pkey is not None and a.prefix_replies:
                        prefix_reply(task, hist + [pkey], obs, codes[0], gi, n)
                    elif PREFIX and pkey is not None:
                        prefix_save(sysm, task, hist + [pkey], kid, gi, n, sum(path_s) + time.time() - t0, obs,
                                    step_s=time.time() - t0)
            if pkey is not None:
                hist.append(pkey)
                if PREFIX:
                    PREFIX.visit(a.system, task["id"], hist)
            rec["exec_s"] = round(time.time() - t0, 3)
            rec.update(take_parts(env))
            spent.append(rec["exec_s"])
            path_s.append(hit_s if rec.get("lazy") else rec["exec_s"])
            if obs.get("screenshot"):
                (d / f"step_{n}.png").write_bytes(obs["screenshot"])
            append_jsonl(d / "traj.jsonl", rec)
            steps = n
            if done:
                break
        # --prefix-replies: a second rollout ending in the same state (a whole trajectory repeated): keep that end state,
        # so the next one needs no re-run for the checker
        ends = PREFIX.note_end(a.system, task["id"], hist) if PREFIX and a.prefix_replies and hist else 0
        if virtual:  # ended (max steps) while still hitting: the checker needs the real final state
            env, virtual = (rerun_materialize(sysm, task, kid, gi, steps + 1, virtual, hist) if a.prefix_replies
                            else materialize(sysm, task, kid, gi, steps + 1, virtual)), None
        if ends >= 2:
            prefix_snapshot(sysm, task, hist, kid, gi, steps + 1)  # before the checker, which may change the desktop
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
    if virtual:
        PREFIX.unpin(virtual[0])
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
    k0 = cached = None  # --prefix-mem: the cache key of this task's after-setup state; the cached source, if any
    lazy0 = False  # --prefix-lazy-start: that state is cached with its reply: no copies, rollouts start on the reply
    if PREFIX and a.prefix_mem:
        k0 = PREFIX.key(a.system, tid, [])
        PREFIX.pin(k0)
        e0 = PREFIX.get(a.system, tid, [])
        if e0 and "mem" in e0 and os.path.exists(f"/proc/{e0['pid']}"):
            cached = e0["mem"]
            lazy0 = a.prefix_lazy_start and bool(e0.get("obs")) and os.path.exists(e0["obs"])
    if PREFIX:
        with PREFIX.lock:
            PREFIX.running.add(tid)
    try:
        with SETUP_SEM:
            check_abort()
            MEM.phase[gi] = "boot"
            if cached:  # fork the rollouts from the cached state after setup: no boot, no setup
                src, (addr, pid) = cached, sysm.info(cached)
                PREFIX.touch(a.system, tid, [], a.epoch)
                log("setup_from_cache", task=tid, g=gi, saved_epoch=e0.get("epoch"), epoch=a.epoch)
            elif BASES:
                src, addr, pid = BASES[gi]
                MEM.add(src, pid, gi)
            else:
                src, addr, pid = boot(sysm, src, gi, tid)
            if not cached:
                MEM.phase[gi] = "setup"
                t0 = time.time()
                make_env(addr).reset(task_config=task)
                time.sleep(5)
                setup_s = time.time() - t0
                log("setup", task=tid, g=gi, secs=round(setup_s, 1))
        log("mem_before_fork", task=tid, g=gi, **MEM.snapshot(gi))

        MEM.phase[gi] = "fork"
        if lazy0:  # placeholders [name, None, None]: each rollout forks its desktop at its first miss
            kids = [(f"lz-{RUN[:12]}-t{gi}-k{k}", None, None) for k in range(a.rollouts)]
            log("fork", task=tid, g=gi, system=a.system, copies=0, secs=0.0, lazy_start=True)
        else:
            with FORK_SEM:
                check_abort()
                # --prefix-mem: no cached state after setup -> one more copy, kept idle as that state
                # (--prefix-replies: the root may be a reply whose snapshot was evicted: it gets one again)
                claim0 = k0 if k0 and not cached and PREFIX.claim(a.system, tid, [], upgrade=a.prefix_replies) else None
                if claim0 and not make_room(sysm):
                    PREFIX.release(claim0)
                    claim0 = None
                    log("prefix_save_skipped", task=tid, g=gi, step=0, reason="budget")
                t0 = time.time()
                kids = sysm.fork(src, a.rollouts + bool(claim0), tid, on_copy=lambda nm, _ad, kp: MEM.add(nm, kp, gi))
                fork_s = round(time.time() - t0, 2)
                if claim0:
                    snap0 = kids.pop()
                    MEM.drop(snap0[0])
                    register_snapshot(claim0, {"system": a.system, "mem": snap0[0], "pid": snap0[2]}, task, [], gi, 0, t0,
                                      setup_s)
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
            reward = rollout(task, domain, k, kid, OUT / domain / f"{name}__g{k}", sysm, gi, start=(k0, e0) if lazy0 else None)
            if a.release_copies and kid[1] is not None:  # free this copy now instead of when the whole group is done
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
        # a cached source stays; a lazy-start placeholder that never got a desktop has no container
        names = ([] if cached else [src]) + [nm for nm, ad, _ in kids if ad is not None and nm not in released]
        sysm.rm(names)
        for nm in names:
            MEM.drop(nm)
        MEM.phase.pop(gi, None)
        if k0:
            PREFIX.unpin(k0)
            PREFIX.release(k0)  # a claim of the after-setup state whose fork failed
        if PREFIX:
            with PREFIX.lock:  # its tree's next use is the next epoch: evicted from first
                PREFIX.running.discard(tid)
                PREFIX.finished.add(tid)


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
    if a.order_by:  # longest first: a long group started last is the tail of the run
        slow = {}
        for d in a.order_by:
            for e in (json.loads(l) for l in open(CWD / d / "events.jsonl") if l.strip()):
                if e["event"] == "rollout_done":
                    slow[e["task"]] = max(slow.get(e["task"], 0.0), e["secs"])
        tasks.sort(key=lambda t: -slow.get(t[1], float("inf")))  # stable: unknown tasks first, in file order
    n = a.groups or len(tasks)
    todo = [(*tasks[i % len(tasks)], i // len(tasks)) for i in range(n)]  # (domain, task, repeat)
    if PREFIX:  # eviction takes from done groups first, then from pending ones latest-scheduled first
        PREFIX.schedule = {tid: i for i, (_, tid, _) in reversed(list(enumerate(todo)))}
    if a.sync_groups and a.release_copies:
        raise SystemExit("--release-copies frees copies as rollouts end; --sync-groups holds them all until the end. Pick one.")
    if a.prefix_mem and not (a.prefix_cache and a.system == "tfork"):
        raise SystemExit("--prefix-mem needs --prefix-cache DIR (its index) and --system tfork")
    if a.ro_rootfs and a.overlay_rootfs:
        raise SystemExit("--ro-rootfs 1 needs --overlay-rootfs 0")
    if a.prefix_cache and a.system == "tfork" and a.ro_rootfs and not a.prefix_mem:
        raise SystemExit("--prefix-cache on disk needs the in-memory cache (--prefix-mem) with --ro-rootfs: tfork-restore "
                         "refuses clones whose snap-ro is shared")
    if a.prefix_cache and a.system == "tfork" and a.overlay_rootfs and not a.prefix_mem:
        raise SystemExit("--prefix-cache on disk needs --overlay-rootfs 0: tfork-restore refuses recursive overlay clones "
                         "(docs/TFORK_RESTORE.md); the in-memory cache (--prefix-mem) clones live, with the overlay flag")
    if (a.prefix_lazy_start or a.prefix_tree or a.prefix_replies) and not (a.prefix_mem and a.prefix_lazy):
        raise SystemExit("--prefix-lazy-start / --prefix-tree / --prefix-replies are for the lazy in-memory cache: add "
                         "--prefix-mem --prefix-lazy")
    if a.prefix_replies and (a.prefix_tree or a.prefix_admit_visits or a.prefix_admit_cost):
        raise SystemExit("--prefix-replies keeps snapshots where rollouts diverge; --prefix-tree / --prefix-admit-visits "
                         "are for the snapshot-per-prefix cache")
    if a.prefix_lazy_start and a.spec_exec:
        raise SystemExit("--prefix-lazy-start: a rollout has no desktop to speculate on until its first miss")
    if SPEC and a.spec_warm:
        dirs = [str((CWD / d).resolve()) for d in a.spec_warm]
        reveals = SPEC.warm(dirs)  # traj.jsonl rows: action, a11y_hit, action_timestamp, step_num
        if BOOK:
            for t in (p for d in dirs for p in glob.glob(f"{d}/**/*__g*/traj.jsonl", recursive=True)):
                for s in (json.loads(l) for l in open(t) if l.strip()):
                    if "action" in s:
                        act = json.loads(s["action"])
                        BOOK.remember(action_key(act, s.get("a11y_hit")), act, s.get("a11y_hit"))
        log("spec_warm", dirs=dirs, reveals=reveals, book_keys=len(BOOK.acts) if BOOK else 0)
    if a.sync_groups:
        FORKED, DONE = Gate(n), Gate(n)
    (OUT / "config.json").write_text(json.dumps(vars(a), indent=1))
    prepare_host(a.system)
    MEM = Mem()
    sysm = Aenv() if a.system == "aenv" else Podman(a.system)
    if PREFIX and a.prefix_keep_since:
        def drop(entry):  # a saved clone (stopped container) or a checkpoint tar
            if "clone" in entry:
                sysm.rm([entry["clone"]])
            elif "path" in entry:
                Path(entry["path"]).unlink(missing_ok=True)
        before = len(PREFIX.index)
        log("prefix_evict", keep_since=a.prefix_keep_since, dropped=PREFIX.evict(a.prefix_keep_since, drop), entries=before)
    if PREFIX and a.prefix_mem:  # snapshots from earlier runs: forget the ones whose container is gone, sample the rest
        with PREFIX.lock:
            mem = [(k, e) for k, e in PREFIX.index.items() if e and "mem" in e]
        dead = [k for k, e in mem if not os.path.exists(f"/proc/{e['pid']}")]
        if dead and a.prefix_tree:  # the tree stays closed: what hung below a gone snapshot goes too
            dead = list(PREFIX.with_descendants(dead))
        if dead:
            drop_snapshots(sysm, dead, "gone")
        for k, e in mem:
            if k not in dead:
                MEM.add(e["mem"], e["pid"], "cache")
        global SIZES
        SIZES = snapshot_sizes()
        log("prefix_mem_start", snapshots=len(mem) - len(dead), gone=len(dead), budget_gib=a.prefix_mem_budget_gib,
            policy=a.prefix_policy)
        threading.Thread(target=budget_guard, args=(sysm,), daemon=True).start()
    log("run_start", system=a.system, spec=a.spec, tasks=len(todo), rollouts=a.rollouts, host_baseline=MEM.snapshot()["host"],
        order=[t[:8] for _, t, _ in todo])
    base = base_fork(sysm, len(todo)) if a.base_fork else None
    try:
        with ThreadPoolExecutor(len(todo) if a.sync_groups else a.parallel or len(todo)) as ex:
            list(ex.map(lambda x: group(sysm, x[0], *x[1]), enumerate(todo)))
    finally:
        if base:
            sysm.rm([base])
            MEM.drop(base)
        if PREFIX:
            PREFIX.save_visits()
    if SPEC:
        (OUT / "spec_summary.json").write_text(json.dumps(SPEC.summary(), indent=1))
    log("run_done", aborted=ABORT.is_set())


if __name__ == "__main__":
    main()
