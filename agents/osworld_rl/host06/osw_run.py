"""OSWorld rollouts on forked desktops with memory profiling. Runs as root on the env host (06).

  sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 venv/bin/python osw_run.py --system tfork --result-dir traces/<run>

Per task group: start a source desktop -> OSWorld task setup -> fork N copies -> N rollouts in parallel -> OSWorld scoring.
Outputs in <result-dir>/: config.json, events.jsonl, mem.jsonl, <domain>/<task>__g<k>/ (chat.jsonl, traj.jsonl, result.txt,
timing.json, step_<n>.png), failed_clones/ (CRIU logs of failed tfork/CKPT clones).
"""
import argparse, contextlib, ctypes, glob, hashlib, json, statistics, os, random, re, resource, shlex, shutil, socket, subprocess, sys, threading, time, traceback
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
ap.add_argument("--stop-repeats", type=int, default=0,
                help="end a rollout (unsolved unless scored so) after this many identical consecutive click/type/drag "
                     "actions on the same element; 0 = off")
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
ap.add_argument("--spec-from", type=int, default=3, help="speculative execution: first step that speculates")
ap.add_argument("--spec-below", type=int, default=0,
                help="speculative execution: only while fewer than this many rollouts are live (the long tail; 0 = always)")
ap.add_argument("--spec-warm", default="", help="comma-separated earlier trace dirs TAGE and the action book learn first")
ap.add_argument("--screen-cache", type=int, default=0,
                help="1: (task, screen, action) seen before -> the model gets the cached next screen at once while the "
                     "rollout's own desktop runs the action in the background; the real screen is checked before the next "
                     "step goes on (mismatch: the model call is redone on the real screen)")
ap.add_argument("--screen-warm", default="", help="comma-separated earlier trace dirs the screen cache learns first")
# policy 2: in-memory prefix tree (port of WukLab/os4agent 2e8a724, its settings: --prefix-mem --prefix-lazy
# --prefix-lazy-start --prefix-tree; their --prefix-replies / --ro-rootfs / --rootfs-check are not ported)
ap.add_argument("--tree-cache", default="",
                help="policy 2: dir of the in-memory prefix tree: hash(task, exact actions so far) -> an idle live tfork clone "
                     "of the desktop there + its reply; a hit returns the reply at once, the rollout's desktop is forked "
                     "from the deepest hit at its next miss (or before scoring). Kept across runs (epochs)")
ap.add_argument("--tree-depth", type=int, default=8, help="--tree-cache: save prefixes up to this many actions")
ap.add_argument("--tree-budget-gib", type=float, default=40, help="--tree-cache: the snapshots' PSS is kept under this")
ap.add_argument("--tree-policy", choices=["lru", "lfu", "gdsf"], default="gdsf", help="--tree-cache: eviction order")
ap.add_argument("--tree-admit-cost", type=float, default=10,
                help="--tree-cache: save a prefix only if (rollouts that reached its parent - 1) x the desktop time from "
                     "the state after setup to it >= this many seconds; 0 = off")
ap.add_argument("--tree-admit-visits", type=int, default=0, help="--tree-cache: save only if >= this many rollouts reached the parent")
ap.add_argument("--tree-lazy-start", type=int, default=1,
                help="--tree-cache: a group whose state after setup is cached (with its reply) forks no copies; each "
                     "rollout gets its desktop at its first miss")
ap.add_argument("--clone-copies-limit", type=int, default=0,
                help="--tree-cache: copies being cloned at once over every clone, first come first served (0 = no limit)")
ap.add_argument("--epoch", type=int, default=-1, help="the GRPO epoch this run is, recorded with --tree-cache entries")
ap.add_argument("--spec-inplace", type=int, default=0,
                help="speculative execution: fork once as an undo copy and run TAGE's top guess on the real desktop "
                     "(a fresh copy runs a step ~13 s slower); on a miss the copy takes over")
ap.add_argument("--spec-slow", type=int, default=0,
                help="speculative execution: only speculate a step if the rollout's previous step's env time was at least "
                     "the median env step time seen so far in the run (spend the --spec-max-forks backups where there "
                     "is the most env time to hide)")
ap.add_argument("--spec-prefork", type=int, default=0,
                help="speculative execution, pre-fork mode: fork the idle desktop while the model thinks, run the chosen "
                     "action and TAGE's guess for the next one on the copy; adopt the copy next step on a hit "
                     "(no backup, no miss penalty). Needs --spec tage --spec-exec 1; replaces the other spec modes")
ap.add_argument("--spec-priority", type=int, default=0,
                help="speculative execution: only rollouts whose projected finish (now + steps left x recent step time) "
                     "is among the --spec-max-forks latest of the live rollouts may speculate: copies go to the "
                     "stragglers that set the epoch's end")
ap.add_argument("--spec-fork-inflight", type=int, default=2,
                help="--spec-prefork: at most this many speculation forks being made at once (a tfork clone under a "
                     "16x8 load takes ~60 s; unbounded speculation forks also delay the rollouts' own fan-out)")
ap.add_argument("--spec-tail-live", type=int, default=0,
                help="--screen-cache + --spec: pre-fork only while at most this many rollouts are live (0 = always); "
                     "forks earlier compete with the desktops for CPU and the cache already serves most steps")
ap.add_argument("--spec-fork-inflight-tail", type=int, default=0,
                help="--spec-prefork: in-flight clone limit once half the run's rollouts have finished (the tail: GPU "
                     "and CPU are free, the stragglers left set the epoch's end); 0 = same as --spec-fork-inflight")
ap.add_argument("--spec-max-forks", type=int, default=0,
                help="speculative execution: at most this many speculation clones at once; a step that finds none free "
                     "doesn't speculate (never queues; 0 = no limit)")
ap.add_argument("--prefix-cache", default="",
                help="dir of the prefix cache: hash(system, task, actions so far) -> checkpoint on disk, shared by epochs")
ap.add_argument("--prefix-depth", type=int, default=0, help="prefix cache: save checkpoints for prefixes up to this long (0 = no limit)")
ap.add_argument("--prefix-clear", type=int, default=0, help="prefix cache: delete every entry before the run starts")
ap.add_argument("--prefix-save", type=int, default=1, help="prefix cache: 0 = only use existing entries, save no new ones")
ap.add_argument("--prefix-restore", choices=["template", "disk"], default="template",
                help="tfork/CKPT prefix cache: template = restore an entry once per group, then tfork-copy it per rollout; "
                     "disk = one tfork-restore per rollout")
# containers (tfork / criu / stock-criu)
ap.add_argument("--image", default="ghcr.io/wuklab/webtop:ubuntu-kde-osworld")
ap.add_argument("--os4agent", default="/mnt/ssd2/os4agent")
ap.add_argument("--storage-conf", default="/mnt/ssd3/podman/storage.conf")
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
from prefix_tree import TreeCache, exact_key  # noqa: E402

OUT = (CWD / a.result_dir).resolve()
OUT.mkdir(parents=True, exist_ok=True)
REPLAY = (CWD / a.replay).resolve() if a.replay else None
RUN = OUT.name.replace("_", "-")[:40]
DESK = HERE / "desk_osw.sh"  # desktop start script, identical on every system
# LibreOffice's GTK3 plugin (libreoffice-gtk3), copied into every source desktop instead of baking a new image: desk_osw.sh
# runs LibreOffice on GTK3 as on the OSWorld VM (on qt5 Calc's tree holds only row 1). It must match the image's
# libreoffice-core exactly; setup/Containerfile.gtk3 is the image alternative.
GTK3_SO, GTK3_LO = HERE / "lo_gtk3" / "libvclplug_gtk3lo.so", "4:24.2.7-0ubuntu0.24.04.7"
LO_DIR = "/usr/lib/libreoffice/program/"
PORTS = ("5000", "9222", "8006", "8080")  # OSWorld server, Chrome CDP, VNC, VLC
SPEC = OnlineTage(max(a.spec_topk, a.spec_exec)) if a.spec == "tage" or a.spec_exec else None
BOOK = ActionBook() if a.spec_exec else None
PREFIX = PrefixCache(str((CWD / a.prefix_cache).resolve()), a.prefix_depth) if a.prefix_cache else None
TREE = TreeCache(str((CWD / a.tree_cache).resolve()), a.tree_depth) if a.tree_cache else None  # policy 2
LOCK, ENV_LOCK, SPEC_LOCK = threading.Lock(), threading.Lock(), threading.Lock()
FORK_SEM = threading.Semaphore(a.fork_concurrency)
BG_RM = []  # threads removing desktops that adopt() replaced
LIVE = [0]  # rollouts running now, across all groups (--spec-below)
SPEC_SLOTS = threading.Semaphore(a.spec_max_forks) if a.spec_max_forks else None  # try-acquired, never waited on
SPEC_FORKING = threading.Semaphore(a.spec_fork_inflight)  # pre-fork clones in progress (try-acquired)
SPEC_FORKING_TAIL = threading.Semaphore(a.spec_fork_inflight_tail) if a.spec_fork_inflight_tail else SPEC_FORKING
STARTED, TOTAL = [0], [0]  # rollouts started / in the run: pre-fork waits until every group has fanned out
BG_SAVES = []  # threads finishing prefix-cache saves (dump wait + stop + register): joined at the end of the run
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
    """--clone-copies-limit (policy 2): at most `limit` copies being cloned at once (a clone counts its copies), in
    arrival order; a clone larger than the limit runs alone. limit 0: no limit."""

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


CLONES = CopyLimit(a.clone_copies_limit if TREE else 0)


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
    snap = b + "/snap-ro"
    if os.path.islink(snap):  # clone of a clone: a link to the group's snapshot, which every desktop of the group sits on
        os.remove(snap)
    elif os.path.isdir(snap):
        subprocess.run(["btrfs", "subvolume", "delete", snap], capture_output=True)
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
        self.dumped = set()  # desktops with a --persistent save: their next save is an incremental dump on top of it
        self.templates, self.tmpl_locks, self.tmpl_lock = {}, {}, threading.Lock()  # (group, cache clone) -> template
        self.tmpl_waiting, self.tmpl_pool = {}, {}  # (group, clone) -> loads queued / copies forked for them
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
        check_lo(self.p("exec", name, "dpkg-query", "-W", "-f=${Version}", "libreoffice-core").stdout, name)
        self.p("cp", str(GTK3_SO), f"{name}:{LO_DIR}")
        return name, *self.info(name)

    def recover_source(self, src, **fields):
        """After a failed clone: a CRIU that died mid-dump (e.g. exit(1) in its SIGCHLD handler when a task segfaults
        under the parasite) leaves the source's network locked (an nftables table CRIU-* dropping all traffic) and maybe
        its cgroup frozen: the desktop runs but nothing reaches it. Remove both. Only called once the clone has exited."""
        try:
            pid = int(self.p("inspect", "-f", "{{.State.Pid}}", src, check=False).stdout.strip() or 0)
            if not pid:
                return
            ns = ["nsenter", "-t", str(pid), "-n"]
            tables = re.findall(r"table (\S+) (CRIU-\S+)", subprocess.run(ns + ["nft", "list", "tables"], capture_output=True, text=True).stdout)
            for fam, t in tables:
                subprocess.run(ns + ["nft", "delete", "table", fam, t], capture_output=True)
            cg = "/sys/fs/cgroup" + open(f"/proc/{pid}/cgroup").read().strip().split("::", 1)[1]
            frozen = open(f"{cg}/cgroup.freeze").read().strip() == "1"
            if frozen:
                open(f"{cg}/cgroup.freeze", "w").write("0")
            if tables or frozen:
                log("criu_lock_recovered", src=src, tables=[t for _, t in tables], unfroze=frozen, **fields)
        except Exception as e:  # best effort: the next step's request times out as before
            log("criu_lock_recover_failed", src=src, error=repr(e)[-200:], **fields)

    _src_locks, _src_locks_guard = {}, threading.Lock()

    def _src_lock(self, src):
        """--tree-cache: clones of one source one at a time (two rollouts forking one snapshot together fail in CRIU's
        seize, "zombie <init> found while seizing", or its RPC, "File exists")."""
        with self._src_locks_guard:
            return self._src_locks.setdefault(src, threading.Lock())

    def _clone(self, src, name, flags, tag, tries=5, backoff=20, **fields):
        """One `container clone --live` with up to `tries` attempts (backoff 20/40/60/80 s by default). -> stdout"""
        if TREE:
            with self._src_lock(src):
                return self._clone_once(src, name, flags, tag, tries, backoff, **fields)
        return self._clone_once(src, name, flags, tag, tries, backoff, **fields)

    def _clone_once(self, src, name, flags, tag, tries, backoff, **fields):
        n = next((int(f.split("=", 1)[1]) for f in flags if f.startswith("--copies=")), 1)
        for attempt in range(tries):
            if attempt:
                time.sleep(backoff * attempt)
            with CLONES.take(n) as waited:  # --clone-copies-limit (policy 2; a no-op otherwise); free during backoff
                t0 = time.time()
                env = {**self.env, "PODMAN_TFORK_NO_REAP": "1"}  # keep failed bundles so their logs can be saved
                r = self.p("container", "clone", "--live", *flags, "--name", name, src, check=False, env=env)
            ok = r.returncode == 0
            log(tag, **fields, attempt=attempt, ok=ok, secs=round(time.time() - t0, 3), why="" if ok else keep_failed_clone(r.stderr),
                **({"wait_s": round(waited, 2)} if TREE else {}))
            if TREE and not ok and "no such container" in r.stderr:  # the source is gone: retrying can't help
                raise RuntimeError(f"{tag}: source {src[:12]} is gone")
            if not ok:
                self.recover_source(src, **fields)
            if ok:
                return r.stdout
        raise RuntimeError(f"{tag} failed {tries}x")

    def fork(self, src, n, task, on_copy=lambda *_: None, part="", spec=False):
        """-> [(name, addr, pid)]. part keeps clone names unique when one source is forked several times.
        spec: a speculation fork -- one attempt (a failure just means the step runs normally), no disk image."""
        ghost = f"--tfork-ghost-limit={64 << 20}"
        if self.system in ("tfork", "criu"):
            self.p("exec", src, "true")  # let tini reap exec children before the freeze
            time.sleep(0.1)
        if self.system == "tfork":
            flags = [f"--copies={n}", *([] if spec else ["--persistent=async"]), "--tfork-tcp-close", ghost]
            if a.overlay_rootfs:
                flags.append("--tfork-overlay-btrfs")
            names = container_ids(self._clone(src, f"{src}-k{part}", flags, "tfork_clone", tries=1 if spec else 5, task=task))
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

    # ---- policy 2 (--tree-cache): idle live copies as snapshots
    def snap_mem(self, name, label):
        """An idle live copy of a running desktop (a tree snapshot); the desktop keeps running."""
        self.p("exec", name, "true")
        time.sleep(0.2)  # as fork(): let tini reap the exec child, or CRIU finds a zombie while seizing
        flags = ["--copies=1", "--tfork-tcp-close", f"--tfork-ghost-limit={64 << 20}"]
        clone = container_ids(self._clone(name, f"pfx-{RUN[:20]}-{label[:12]}", flags, "prefix_clone"))[0]
        return {"system": self.system, "mem": clone, "pid": self.info(clone)[1]}

    _batches, _batches_guard = {}, threading.Lock()

    def load_shared(self, entry, name, wait=1.0):
        """Fork a tree snapshot into a rollout desktop; rollouts that ask for the same snapshot within `wait` s share one
        `--copies=k` clone. -> (name, addr, pid)"""
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
                flags = [f"--copies={b['n']}", "--tfork-tcp-close", f"--tfork-ghost-limit={64 << 20}"]
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
        wait_ready(addr)
        return new, addr, pid

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
        """Checkpoint a running desktop to disk (--prefix-cache); it keeps running.
        tfork / CKPT: a --persistent clone, stopped once its dump is done -- only its image and rootfs snapshot stay
        (default rootfs mode: tfork-restore refuses overlay clones of overlay clones). stock-criu: checkpoint --export."""
        if self.system in ("tfork", "criu"):
            clone = f"pfx-{os.path.basename(path)}-{os.urandom(2).hex()}"  # suffix: another cache dir may hold this prefix
            with FORK_SEM:  # same --fork-concurrency limit as forks: unthrottled clones time out in CRIU's restore wait
                self.p("exec", name, "true")  # as fork(): let tini reap exec children before the freeze
                time.sleep(0.1)
                # a rollout's deeper saves keep only the pages changed since its previous save (its parent entry, which
                # restore reads through; parents are never removed before their children: entries go only on --prefix-clear)
                incr = ["--with-previous"] if name in self.dumped else []
                self._clone(name, clone, ["--copies=1", "--persistent=async", *incr, "--tfork-tcp-close",
                                          f"--tfork-ghost-limit={64 << 20}"],
                            "prefix_clone", tries=1, incremental=bool(incr))  # a failed save only costs a cache entry
                self.dumped.add(name)
            def finish():  # the dump runs async; the entry is restorable (and the clone can stop) once it is done
                t0 = time.time()
                while (st := self.p("inspect", "-f", "{{.Tfork.DumpStatus}}", clone).stdout.strip()) != "done":
                    if st == "failed":  # dumpd: a page-writing helper failed, the image is incomplete
                        self.rm([clone])
                        raise RuntimeError(f"prefix clone {clone}: dump failed (incomplete image)")
                    if time.time() - t0 > a.obs_timeout:
                        raise RuntimeError(f"prefix clone {clone} dump still {st!r} after {a.obs_timeout} s")
                    time.sleep(1)
                self.p("stop", "-t", "0", clone)
                return {"system": self.system, "clone": clone}
            return finish
        self.p("container", "checkpoint", "--leave-running", "--tcp-established", "--compress=none", f"--export={path}.tar",
               name, timeout=a.obs_timeout)
        return {"system": self.system, "path": f"{path}.tar"}

    def load(self, entry, name, gi=None):
        """A new desktop restored from a save() checkpoint. -> (name, addr, pid)"""
        if entry.get("clone") and a.prefix_restore == "template":
            return self._load_from_template(entry["clone"], gi)
        if entry.get("clone"):
            self.p("container", "tfork-restore", "--name", name, entry["clone"], timeout=a.obs_timeout)
            return (name, *self.info(name))
        pub = [x for p in PORTS for x in ("--publish", p)] if self.slirp else []
        self.p("container", "restore", f"--import={entry['path']}", "--name", name, "--ignore-static-ip",
               "--ignore-static-mac", *pub, timeout=a.obs_timeout)
        return (name, *self.info(name))

    def _load_from_template(self, clone, gi):
        """--prefix-restore template: the group's first load of an entry restores it (from disk) into a running template
        desktop; every load then gets a tfork copy of that template -- no disk reads, memory shared copy-on-write."""
        key = (gi, clone)
        with self.tmpl_lock:
            lock = self.tmpl_locks.setdefault(key, threading.Lock())
            self.tmpl_waiting[key] = self.tmpl_waiting.get(key, 0) + 1
        with lock:  # one restore per entry and group; the holder forks a copy for itself and every load queued behind it
            with self.tmpl_lock:
                self.tmpl_waiting[key] -= 1
            pool = self.tmpl_pool.setdefault(key, [])
            if not pool:
                tmpl = self.templates.get(key)
                if tmpl is None:
                    tmpl, t0 = f"tmpl-g{gi}-{clone[4:]}", time.time()
                    self.p("container", "tfork-restore", "--name", tmpl, clone, timeout=a.obs_timeout)
                    self.templates[key] = tmpl
                    MEM.add(tmpl, self.info(tmpl)[1], gi)
                    log("prefix_template", g=gi, clone=clone, secs=round(time.time() - t0, 2))
                with self.tmpl_lock:
                    n = 1 + self.tmpl_waiting[key]
                with FORK_SEM:
                    self.p("exec", tmpl, "true")  # as fork(): let tini reap exec children before the freeze
                    time.sleep(0.1)
                    # a just-restored desktop's netlink sockets hold its new netns' events for a moment ("socket has
                    # data to read"): retry quickly instead of the 20 s backoff.
                    # Overlay copies share the template's files and page cache (rollback under load 10.6 vs 18.8 s,
                    # ~190 vs ~410 MiB per copy), but an overlay rootfs can't be the source of a later save: plain
                    # copies when this run saves.
                    ov = [] if a.prefix_save else ["--tfork-overlay-btrfs"]
                    pool += container_ids(self._clone(tmpl, f"{tmpl}-{os.urandom(2).hex()}", [
                        f"--copies={n}", "--tfork-tcp-close", f"--tfork-ghost-limit={64 << 20}", *ov], "prefix_fork",
                        tries=5, backoff=2, g=gi, copies=n))
            nm = pool.pop()
        return (nm, *self.info(nm))

    def drop_templates(self, gi):
        """Remove the group's prefix templates (its copies are independent desktops)."""
        with self.tmpl_lock:  # templates + copies forked for loads that never claimed them
            names = [t for (g, _), t in self.templates.items() if g == gi]
            names += [c for (g, _), cs in self.tmpl_pool.items() if g == gi for c in cs]
            self.templates = {k: t for k, t in self.templates.items() if k[0] != gi}
            self.tmpl_pool = {k: cs for k, cs in self.tmpl_pool.items() if k[0] != gi}
        self.rm(names)
        for nm in names:
            MEM.drop(nm)

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

    def stop(self, names):
        """Free a desktop's memory but keep its bundle: an overlay fork's lower layer lives in its parent's bundle."""
        if names:
            self.p("stop", "-t", "0", *names, check=False, timeout=300)


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
        check_lo(self.cli("exec", sb, "--", "dpkg-query", "-W", "-f=${Version}", "libreoffice-core").stdout, sb)
        self.cli("upload", sb, str(GTK3_SO), LO_DIR + GTK3_SO.name)
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

    def drop_templates(self, _gi): pass

    def load(self, entry, _name, _gi=None):
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


def check_lo(version, where):
    """The copied GTK3 plugin only loads into the libreoffice-core it was built for; otherwise LibreOffice silently
    falls back to qt5 and Calc's tree loses every row but the first."""
    if version.strip() != GTK3_LO:
        raise RuntimeError(f"{where}: libreoffice-core {version.strip()!r}, but lo_gtk3/ is for {GTK3_LO}: re-extract it")


ENV_TIMES = []  # every env step time of the run so far (--spec-slow)
PROJ = {}  # --spec-priority: live rollout -> projected finish time (epoch seconds)


def straggler(rid):
    """--spec-priority: is rollout `rid` among the --spec-max-forks live rollouts projected to finish last?"""
    with LOCK:
        if rid not in PROJ:
            return False
        k = a.spec_max_forks or len(PROJ)
        return PROJ[rid] >= sorted(PROJ.values(), reverse=True)[min(k, len(PROJ)) - 1]
REPEATABLE = {"click", "double_click", "right_click", "type", "drag"}  # actions --stop-repeats counts
NUDGE = json.dumps({"command": "xdotool mousemove_relative 1 0 sleep 0.2 mousemove_relative -- -1 0", "shell": True}).encode()


def make_env(addr):
    with ENV_LOCK:  # the provider factory is module-global
        dem.create_vm_manager_and_provider = lambda *_a, **_k: (FixedManager(), FixedProvider(addr))
        env = DesktopEnv(provider_name="docker", path_to_vm=f"external-{addr}", action_space="pyautogui",
                         require_a11y_tree=True, headless=True, recording_update="off")
    # One long wait instead of OSWorld's 3 x 60 s: a timed-out request keeps running in the desktop's server, so
    # retrying a slow (CPU-starved) desktop only stacks more tree builds on it.
    env.controller.request_timeout, env.controller.retry_times = a.obs_timeout, 1
    # LibreOffice (GTK3) reports everything below its menubar ~27px too high until the pointer moves over its window;
    # a 1px move and back before every observation (reset, step, refetch) makes the tree's coordinates exact
    get_obs = env._get_obs
    def nudged_obs():
        try:
            urllib.request.urlopen(urllib.request.Request(f"{env.controller.http_server}/execute", data=NUDGE,
                                                          headers={"Content-Type": "application/json"}), timeout=10).read()
        except Exception:
            pass  # an observation without the nudge only risks LibreOffice's offset
        return get_obs()
    env._get_obs = nudged_obs
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
    # --tree-cache on tfork: the relay survives the clone and must not be restarted -- one started through `podman exec`
    # is outside the desktop's process tree and CRIU can't seize it when the copy is cloned again (a tree snapshot)
    relay = relay_restart(task) if task and not (TREE and getattr(sysm, "system", None) == "tfork") else None
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
                     "rows": [[r, n, list(b)] for r, n, b in rows],
                     "t": st.get("t")}  # recorded model-call times (--spec-envbound compares them with env time)
        if self.log:
            append_jsonl(self.log, self.last)
        return st.get("response", ""), [code]


# ---------------------------------------------------------------- screen cache (--screen-cache)

CLOCK = re.compile(r"\b\d{1,2}:\d{2}( [AP]M)?\b")  # the taskbar clock: the only text that differs between equal screens


class CachedTree:
    """An accessibility tree known only as the agent's linearized form (a cached screen): linearize() returns it as is."""

    def __init__(self, text, rows):
        self.text, self.rows = text, [(r, n, tuple(b)) for r, n, b in rows]


import a11y_owl_agent as _agent_mod  # noqa: E402
import functools  # noqa: E402
# --screen-cache: one parse per tree. It reads each real screen up to 4 times (check, cache, retarget, the agent); at
# 128 rollouts in one process the extra parsing saturated the GIL (~1.5 s per step). Callers only read the result.
_linearize = functools.lru_cache(maxsize=512)(_agent_mod.linearize) if a.screen_cache else _agent_mod.linearize
_agent_mod.linearize = linearize = lambda t: (t.text, t.rows) if isinstance(t, CachedTree) else _linearize(t)


class ScreenCache:
    """(task, screen the model saw, action key) -> the screen after the action: text + rows as linearize gives them,
    and the screenshot. Filled from earlier traces (--screen-warm) and by every real step of this run."""

    def __init__(self):
        self.d, self.lock = {}, threading.Lock()

    @staticmethod
    def key(task, text, akey):
        return task, hashlib.sha1(CLOCK.sub("", text).encode()).hexdigest(), akey

    def get(self, task, text, akey):
        with self.lock:
            return self.d.get(self.key(task, text, akey))

    def put(self, task, text, akey, obs):
        """A real step: the latest result wins."""
        nt, rows = linearize(obs["accessibility_tree"])
        with self.lock:
            self.d[self.key(task, text, akey)] = (nt, [[r, n, list(b)] for r, n, b in rows], obs.get("screenshot"))

    def warm(self, dirs):
        """chat.jsonl line j (the screen the model saw at step j+1, its action in traj.jsonl) -> line j+1's screen."""
        n = 0
        for d in (p for x in dirs for p in glob.glob(f"{x}/*/*__g*")):
            try:
                ch = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
                tr = [json.loads(l) for l in open(f"{d}/traj.jsonl")]
            except OSError:
                continue
            task = os.path.basename(d).split("__g")[0]
            seen = [screen_text(c) for c in ch]
            for j in range(min(len(ch), len(tr)) - 1):
                akey = action_key(json.loads(tr[j]["action"]), tr[j].get("a11y_hit"))
                if akey is None or seen[j] is None or seen[j + 1] is None:
                    continue
                png = Path(f"{d}/step_{j + 1}.png")
                with self.lock:
                    self.d.setdefault(self.key(task, seen[j], akey), (seen[j + 1], ch[j + 1]["rows"], png))
                n += 1
        return n

    @staticmethod
    def obs(entry):
        text, rows, png = entry
        return {"accessibility_tree": CachedTree(text, rows),
                "screenshot": png.read_bytes() if isinstance(png, Path) and png.exists() else png}


def screen_text(chat_line):
    """The tree text of a logged prompt (A11yAgent's chat.jsonl), or None (replays log no prompt)."""
    msgs = chat_line.get("messages")
    if not msgs:
        return None
    c = msgs[-1]["content"]
    c = c[-1]["text"] if isinstance(c, list) else c
    if "Accessibility tree:\n" not in c:
        return None
    return c.split("Accessibility tree:\n", 1)[1].rsplit("\n\nNext action?", 1)[0]


def real_code(agent, codes, act, seen_rows, real_obs):
    """The step's code for the real desktop: the agent's own when it has no element targets to move (DONE/FAIL/WAIT,
    or a replay that fell back to recorded coordinates), else retargeted; the agent's code if retargeting fails."""
    if codes[0] in ("DONE", "FAIL", "WAIT") or (agent.last or {}).get("replay") == "coords":
        return codes[0]
    try:
        return retarget(act, seen_rows, real_obs)
    except Exception:
        return codes[0]


def retarget(act, seen_rows, real_obs):
    """The action's code on the real desktop: its targets re-found by (role, name) in the real tree (a cached screen's
    boxes may sit elsewhere). Falls back to the seen boxes if a target is missing."""
    _, real = linearize(real_obs["accessibility_tree"])
    act = dict(act)
    seen = [(r, n, tuple(b)) for r, n, b in seen_rows]
    for k in ("id", "from", "to"):
        if isinstance(act.get(k), int) and 0 <= act[k] < len(seen):
            j = refind(seen[act[k]], real)
            if j is None:
                return to_code(dict(act), seen)
            act[k] = j
    return to_code(act, real)


class BgStep:
    """Runs a served (cached) step on the rollout's real desktop while the model thinks about the next one."""

    def __init__(self, env, code, seen_text, expect, task, akey, wait=None):
        """wait: an event to wait for before touching the desktop (prefix+spec: this step's copy being forked)."""
        self.args, self.wait = (env, code, seen_text, expect, task, akey), wait
        self.out = self.err = None
        self.th = threading.Thread(target=self._run, daemon=True)
        self.th.start()

    def _run(self):
        env, code, seen_text, expect, task, akey = self.args
        t0 = time.time()
        try:
            if self.wait is not None:
                self.wait.wait(timeout=a.obs_timeout)  # the copy must be the state before this action
            obs, _, done, _ = env.step(code)
            if not done:
                obs = observe(env, obs)
            got = linearize(obs["accessibility_tree"])[0]
            SCACHE.put(task, seen_text, akey, obs)
            self.out = (CLOCK.sub("", got) == CLOCK.sub("", expect), obs, round(time.time() - t0, 3))
        except BaseException as e:  # noqa: BLE001 (re-raised in result())
            self.err = e

    def result(self):
        """-> (the served screen was right, the real observation, background secs, secs waited here)"""
        t0 = time.time()
        self.th.join()
        if self.err:
            raise self.err
        return (*self.out, round(time.time() - t0, 3))


def rewind(agent):
    """Undo the agent's last predict (its step is redone on another screen)."""
    if hasattr(agent, "n"):
        agent.n -= 1
    elif getattr(agent, "hist", None):
        agent.hist.pop()


SCACHE = ScreenCache() if a.screen_cache else None
SPEC_AFTER_HIT = bool(SCACHE and a.spec_prefork and a.spec != "off")  # prefix+spec: the combined-mode rules above


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


def bg_rm(sysm, names):
    """Remove desktops off the rollout's path (podman rm under load: 5-30 s)."""
    for nm in names:
        MEM.drop(nm)
    if names:
        t = threading.Thread(target=sysm.rm, args=(list(names),), daemon=True)
        t.start()
        BG_RM.append(t)


def adopt(sysm, kid, new, gi, task):
    """Rollout copy `kid` ([name, addr, pid], updated in place) becomes desktop `new`; the old one is freed.
    --tree-lazy-start: a rollout that has no desktop yet has addr None."""
    if kid[1] is not None:
        bg_rm(sysm, [kid[0]])
    kid[:] = list(new)
    MEM.add(new[0], new[2], gi)
    return task_env(new[1], task)


class Speculation:
    """--spec-exec: while the model thinks, fork the rollout's desktop once per TAGE guess and run each guess.
    Nothing here blocks the rollout: the model starts right away; on a miss the rollout only waits until tfork has
    copied (and so unfrozen) its desktop, on a hit only for that one guess; forks are removed in the background."""

    def __init__(self, sysm, kid, task, guesses, rows, gi, part):
        self.sysm, self.task, self.gi, self.t0 = sysm, task, gi, time.time()
        self.plan = [(g, c) for g in guesses if (c := BOOK.code_for(g, rows))][:a.spec_exec]
        self.forks, self.err, self.fork_s = [], None, 0.0
        self.results = [None] * len(self.plan)  # (env, obs, done) per guess, set by its thread
        self.ran = [threading.Event() for _ in self.plan]  # guess i finished (or failed)
        self.forked = threading.Event()  # tfork is done with the source desktop
        if self.plan and SPEC_SLOTS and not SPEC_SLOTS.acquire(blocking=False):
            self.plan = []  # every speculation slot is busy: this step runs normally
        if self.plan:
            threading.Thread(target=self._run, args=(kid[0], part), daemon=True).start()

    def _run(self, src, part):
        try:
            self._fork(src, part)
        finally:
            if SPEC_SLOTS:
                SPEC_SLOTS.release()  # the slot covers the clone only, not the guesses running on its copies

    def _fork(self, src, part):
        try:
            self.forks = [list(f) for f in self.sysm.fork(src, len(self.plan), self.task["id"], part=part, spec=True)]
            for nm, _, pid in self.forks:
                MEM.add(nm, pid, self.gi)
        except Exception as e:
            self.err = repr(e)[-300:]
            for ev in self.ran:
                ev.set()
            return
        finally:
            self.forked.set()
        self.fork_s = time.time() - self.t0

        def run_guess(i):
            try:
                fixup_copies(self.sysm, [self.forks[i]], self.task)
                env = task_env(self.forks[i][1], self.task)
                obs, _, done, _ = env.step(self.plan[i][1])
                self.results[i] = (env, (obs if done else observe(env, obs)), done)
            except Exception as e:  # also: the fork was removed under it after a miss
                self.err = repr(e)[-300:]
            finally:
                self.ran[i].set()
        for i in range(len(self.plan)):
            threading.Thread(target=run_guess, args=(i,), daemon=True).start()

    def finish(self, key):
        """-> (fork desktop, env, obs, done) of the fork that ran `key`, or None. Every other fork is freed."""
        if not self.plan:
            return None
        t_wait = time.time()
        idx = next((i for i, (g, _) in enumerate(self.plan) if g == key), None)
        if idx is not None:
            self.ran[idx].wait()
            if self.results[idx] is None:  # fork or guess failed: run the action for real
                idx = None
        self.forked.wait()  # a miss: the real desktop is frozen until tfork has copied it
        bg_rm(self.sysm, [f[0] for j, f in enumerate(self.forks) if j != idx])
        log("spec_exec", task=self.task["id"], g=self.gi, guesses=len(self.plan), hit=idx, fork_s=round(self.fork_s, 2),
            total_s=round(time.time() - self.t0, 2), waited_s=round(time.time() - t_wait, 2), error=self.err)
        return (self.forks[idx], *self.results[idx]) if idx is not None else None


class InPlaceSpec:
    """--spec-inplace: fork the desktop once as an undo copy (the state before the action), then run TAGE's top guess on
    the real desktop while the model thinks -- a fresh copy runs a step ~13 s slower than the warm desktop. Hit: the step
    is already done here; the copy is dropped. Miss: the copy, prepared meanwhile, becomes the desktop and the model's
    action runs on it. The guess runs only once the copy exists: a failed fork leaves the real desktop untouched."""

    def __init__(self, sysm, kid, task, guesses, rows, gi, part, retired):
        self.sysm, self.kid, self.task, self.gi, self.retired, self.t0 = sysm, kid, task, gi, retired, time.time()
        self.plan = [(g, c) for g in guesses if (c := BOOK.code_for(g, rows))][:1]
        self.backup = self.backup_env = self.result = self.err = None
        self.fork_s = 0.0
        self.forked, self.ran, self.ready = threading.Event(), threading.Event(), threading.Event()
        if self.plan and SPEC_SLOTS and not SPEC_SLOTS.acquire(blocking=False):
            self.plan = []  # every speculation slot is busy: this step runs normally
        if self.plan:
            threading.Thread(target=self._run, args=(kid[0], kid[1], part), daemon=True).start()

    def _run(self, src, addr, part):
        try:
            try:
                self.backup = list(self.sysm.fork(src, 1, self.task["id"], part=part, spec=True)[0])
                MEM.add(self.backup[0], self.backup[2], self.gi)
            finally:
                if SPEC_SLOTS:
                    SPEC_SLOTS.release()
        except Exception as e:
            self.err = repr(e)[-300:]
            self.ran.set()
            self.ready.set()
            return
        finally:
            self.forked.set()  # the real desktop is unfrozen
        self.fork_s = time.time() - self.t0

        def guess():  # on the real desktop
            try:
                env = task_env(addr, self.task)
                obs, _, done, _ = env.step(self.plan[0][1])
                self.result = (env, obs if done else observe(env, obs), done)
            except Exception as e:
                self.err = repr(e)[-300:]
            finally:
                self.ran.set()

        def prepare():  # the undo copy, ready to take over on a miss
            try:
                fixup_copies(self.sysm, [self.backup], self.task)
                self.backup_env = task_env(self.backup[1], self.task)
            except Exception as e:
                self.err = repr(e)[-300:]
            finally:
                self.ready.set()
        threading.Thread(target=guess, daemon=True).start()
        threading.Thread(target=prepare, daemon=True).start()

    def _switch(self):
        """The real desktop ran the wrong action: the undo copy becomes the rollout's desktop. -> ("switch", env)"""
        self.ready.wait()
        env = self.backup_env or task_env(self.backup[1], self.task)
        old = self.kid[0]
        MEM.drop(old)
        self.retired.append(old)  # stopped now, removed when the rollout ends (like an adopted fork's parent)
        threading.Thread(target=self.sysm.stop, args=([old],), daemon=True).start()
        self.kid[:] = self.backup
        return "switch", env

    def finish(self, key):
        """-> (None, env, obs, done) on a hit, ("switch", env) on a miss, None if nothing was speculated."""
        if not self.plan:
            return None
        t_wait = time.time()
        self.forked.wait()
        if self.backup is None:  # fork failed: the guess never ran, the desktop is as it was
            outcome, ret = "no_fork", None
        elif self.plan[0][0] == key:
            self.ran.wait()
            if self.result is not None:
                bg_rm(self.sysm, [self.backup[0]])
                outcome, ret = "hit", (None, *self.result)
            else:  # the guess failed part way: the desktop's state is unknown, take the clean copy
                outcome, ret = "guess_failed", self._switch()
        else:
            outcome, ret = "miss", self._switch()
        log("spec_exec", task=self.task["id"], g=self.gi, guesses=1, inplace=True, outcome=outcome,
            hit=0 if outcome == "hit" else None, fork_s=round(self.fork_s, 2), total_s=round(time.time() - self.t0, 2),
            waited_s=round(time.time() - t_wait, 2), error=self.err)
        return ret


class PreFork:
    """--spec-prefork: while the model thinks about action n the desktop is idle, so fork it then (tfork's freeze and
    copy cost the rollout nothing) and warm the copy (a fresh copy's first tree is slow). Once action n is known, run it
    on the copy too, then TAGE's guess for action n+1. Next step: if the model chose that guess and the copy's tree
    after action n matches the real desktop's, the copy (one action ahead) becomes the desktop; otherwise it is dropped.
    The real desktop is never touched, so a miss costs nothing."""

    def __init__(self, sysm, kid, task, gi, part, after=None):
        """after: --screen-cache + --spec, the previous step was served from the cache: its BgStep is still running the
        action on the desktop; fork once it is done (median ~7 s, inside the model's think time)."""
        self.sysm, self.task, self.gi, self.t0, self.after = sysm, task, gi, time.time(), after
        self.fork = self.env = self.result = self.err = self.guess = self.rows_after = self.code = None
        self.hist, self.fork_s, self.adopted, self.dropped, self.slot = [], 0.0, False, False, threading.Lock()
        self.unusable = False  # the guess had no code on the copy's screen
        self.forked, self.guessed, self.ran, self.go_ev = (threading.Event() for _ in range(4))
        self.ok = not SPEC_SLOTS or SPEC_SLOTS.acquire(blocking=False)
        self.fsem = None
        if self.ok and after is None and not self._take_fork_slot():  # enough clones in progress already
            if SPEC_SLOTS:
                SPEC_SLOTS.release()
            self.ok = False
        if self.ok:
            threading.Thread(target=self._run, args=(kid[0], part), daemon=True).start()
        else:  # every speculation slot is busy: nothing this step
            for ev in (self.forked, self.guessed, self.ran):
                ev.set()

    def _take_fork_slot(self):
        """A --spec-fork-inflight slot (more in the tail: half the run's rollouts done), without waiting. -> got it"""
        with LOCK:
            fsem = SPEC_FORKING_TAIL if TOTAL[0] and LIVE[0] <= TOTAL[0] // 2 else SPEC_FORKING
        if fsem.acquire(blocking=False):
            self.fsem = fsem
            return True
        return False

    def release(self):
        """Give the --spec-max-forks slot back (once)."""
        if SPEC_SLOTS and self.ok and self.slot.acquire(blocking=False):
            SPEC_SLOTS.release()

    def go(self, code, key, hist):
        """Action n is known (code None: cancel)."""
        self.code, self.hist = code, list(hist) + [key]
        self.go_ev.set()

    def _run(self, src, part):
        try:
            if self.after is not None:
                self.after.th.join()  # the desktop is at the previous step's state once its background run is done
                if self.dropped:  # this step turned out to be a cache hit meanwhile: no copy (drop() frees the slot)
                    return
                if not self._take_fork_slot():  # the fork slot only now, so the wait never holds one
                    self.release()
                    self.ok = False  # finish() then sees a pre-fork that never ran
                    return
            try:  # the slot stays taken until the copy is adopted or removed: --spec-max-forks caps live copies
                self.fork = list(self.sysm.fork(src, 1, self.task["id"], part=part, spec=True)[0])
                MEM.add(self.fork[0], self.fork[2], self.gi)
            finally:
                self.fsem.release()
                self.forked.set()
            self.fork_s = time.time() - self.t0
            fixup_copies(self.sysm, [self.fork], self.task)
            self.env = task_env(self.fork[1], self.task)
            observe(self.env)  # warm the copy while the model is still thinking
            self.go_ev.wait()
            if self.code is None:
                return
            with SPEC_LOCK:  # the guess only needs the action history: known before the copy runs action n, so a
                guesses = SPEC.tage.predict(str(self.task["id"]), self.hist)[0]  # different model answer drops it at once
            self.guess = guesses[0] if guesses else None
            self.guessed.set()
            if self.guess is None:
                return
            obs, _, done, _ = self.env.step(self.code)  # action n
            if done or self.dropped:
                return
            obs = observe(self.env, obs)
            rows = linearize(obs["accessibility_tree"])[1]
            self.rows_after = {(r[0], r[1]) for r in rows}
            code = BOOK.code_for(self.guess, rows)
            if not code or self.dropped:
                self.unusable = not code
                return
            obs, _, done, _ = self.env.step(code)  # the guess for action n+1
            self.result = (self.env, obs if done else observe(self.env, obs), done)
        except Exception as e:
            self.err = repr(e)[-300:]
            if not self.fork:
                self.release()
        finally:
            for ev in (self.forked, self.guessed, self.ran):
                ev.set()

    def finish(self, key, rows_now, env, code):
        """Action n+1 is `key` (`code` on the real desktop's `env`); rows_now: the real desktop's rows after action n.
        -> (copy, env, obs, done) to adopt the copy, ("real", env, obs, done) if the real desktop already ran the action
        (it won the race), or None (run the action normally)."""
        if not self.ok:
            return None
        t_wait = time.time()  # never waits: a copy that has not finished the guess yet is simply not used
        if not self.guessed.is_set():
            outcome = "not_ready"
        elif self.guess is None or self.unusable:
            outcome = "no_guess"
        elif self.guess != key:
            outcome = "miss"  # known early: the copy is dropped before it runs the guess
        elif self.rows_after is None:
            outcome = "not_ready"  # the copy is still replaying action n: its state can't be checked yet
        else:
            now = {(r[0], r[1]) for r in rows_now}
            same = self.rows_after is not None and len(now & self.rows_after) >= 0.9 * max(len(now | self.rows_after), 1)
            if not same:
                outcome = "diverged"
            elif self.ran.is_set():
                outcome = "hit" if self.result is not None else "guess_failed"
            else:  # the copy is part-way through the same action from the same state: race it with the real desktop
                outcome, real = self._race(env, code)
                if outcome == "race_real":
                    log("spec_exec", task=self.task["id"], g=self.gi, guesses=1, prefork=True, outcome=outcome, hit=None,
                        fork_s=round(self.fork_s, 2), total_s=round(time.time() - self.t0, 2),
                        waited_s=round(time.time() - t_wait, 2), error=self.err)
                    self.drop()
                    return ("real", env, *real)
        log("spec_exec", task=self.task["id"], g=self.gi, guesses=1, prefork=True, outcome=outcome,
            hit=0 if outcome in ("hit", "race_copy") else None, fork_s=round(self.fork_s, 2), total_s=round(time.time() - self.t0, 2),
            waited_s=round(time.time() - t_wait, 2), error=self.err)
        if outcome in ("hit", "race_copy"):
            self.adopted = True
            self.release()  # the copy is the rollout's desktop now, not a speculation
            return (self.fork, *self.result)
        self.drop()
        return None

    def _race(self, env, code):
        """Run `code` on the real desktop while the copy finishes the same action; first one done wins.
        -> ("race_copy", None) or ("race_real", (obs, done)); a real-desktop error is raised as on the normal path."""
        res, real_done = {}, threading.Event()

        def real():
            try:
                obs, _, d, _ = env.step(code)
                res["r"] = (obs if d else observe(env, obs), d)
            except Exception as e:  # also: this desktop was stopped because the copy won
                res["e"] = e
            finally:
                real_done.set()
        threading.Thread(target=real, daemon=True).start()
        while True:
            if real_done.is_set():
                if "e" in res:
                    if self.ran.is_set() and self.result is not None:
                        return "race_copy", None
                    raise res["e"]
                return "race_real", res["r"]
            if self.ran.is_set() and self.result is not None:
                return "race_copy", None
            if self.ran.is_set():  # the copy failed: wait for the real desktop
                real_done.wait()
                continue
            time.sleep(0.05)

    def drop(self):
        """Not used: cancel the copy's work and remove it once it exists."""
        if not self.ok or self.adopted or self.dropped:
            return
        self.dropped = True
        self.go(None, None, [])

        def rm():
            self.forked.wait()
            self.ran.wait()
            if self.fork:
                MEM.drop(self.fork[0])
                self.sysm.rm([self.fork[0]])
            self.release()
        t = threading.Thread(target=rm, daemon=True)
        t.start()
        BG_RM.append(t)  # joined before the run exits, or the copy outlives it


def prefix_restore(sysm, entry, task, kid, gi, n):
    """Replace the rollout's desktop with a --prefix-cache checkpoint (the deepest prefix that matched). -> env"""
    t0 = time.time()
    new = sysm.load(entry, f"{kid[0][:24]}-p{n}", gi)
    t1 = time.time()
    fixup_copies(sysm, [new], task)
    t2 = time.time()
    env = adopt(sysm, kid, new, gi, task)
    t3 = time.time()
    log("prefix_restored", task=task["id"], g=gi, step=n, secs=round(t3 - t0, 2),
        load_s=round(t1 - t0, 2), fixup_s=round(t2 - t1, 2), adopt_s=round(t3 - t2, 2))  # adopt: rm old + new env
    return env


def prefix_save(sysm, task, keys, kid, gi, n, obs):
    """Save the rollout's desktop (and the observation it shows) under `keys`, unless the prefix is too deep, saved
    already, or being saved by another rollout."""
    # ponytail: no eviction; stop saving under 60 GiB free on the podman store (an entry is ~0.8 GiB of dump on tfork)
    if a.system != "aenv" and shutil.disk_usage(Path(a.storage_conf).parent).free < 60 << 30:
        return
    k = PREFIX.claim(a.system, task["id"], keys)
    if not k:
        return
    t0 = time.time()

    def done(entry, err=None):
        if err is None:
            log("prefix_saved", task=task["id"], g=gi, step=n, secs=round(time.time() - t0, 2), blocked_s=blocked)
        else:
            log("prefix_save_failed", task=task["id"], g=gi, step=n, error=repr(err)[-300:])
        PREFIX.put(k, entry, obs)

    try:
        r = sysm.save(kid[0], os.path.join(PREFIX.root, k))
    except Exception as e:
        blocked = round(time.time() - t0, 2)
        return done(None, e)
    blocked = round(time.time() - t0, 2)  # what the rollout waited: the clone; tfork/CKPT finish the dump in background
    if not callable(r):
        return done(r)

    def finish():
        try:
            done(r())
        except Exception as e:
            done(None, e)
    t = threading.Thread(target=finish, daemon=True)
    t.start()
    BG_SAVES.append(t)


# ---------------------------------------------------------------- policy 2: in-memory prefix tree (--tree-cache)
# Port of WukLab/os4agent 2e8a724 (osw_run.py --prefix-mem --prefix-lazy --prefix-lazy-start --prefix-tree), same
# names; TREE is its own cache object: --prefix-cache, speculation and the screen cache never see it.

SNAP_EST_MIB = 450  # a new snapshot's PSS once its lineage is gone (their test_mem_snapshot.py: 385-448 MiB)
SIZES = {}  # each snapshot's PSS (MiB) as budget_guard last measured it (replaced whole, never mutated)
EVICT_LOCK = threading.Lock()  # one eviction at a time: concurrent saves picked (and logged) the same victims


def known_sizes():
    """The snapshots' PSS as last measured; one saved since counts SNAP_EST_MIB."""
    sizes = SIZES
    with TREE.lock:
        keys = [k for k, e in TREE.index.items() if e and "mem" in e]
    return {k: sizes.get(k, SNAP_EST_MIB) for k in keys}


def snapshot_sizes():
    """PSS (MiB) of every snapshot in the tree; a snapshot whose container is gone counts 0."""
    ns, out = pids_by_pidns(), {}
    with TREE.lock:
        entries = [(k, e) for k, e in TREE.index.items() if e and "mem" in e]
    for k, e in entries:
        try:
            out[k] = smaps(ns.get(os.readlink(f"/proc/{e['pid']}/ns/pid"), []))["pss_mib"]
        except OSError:
            out[k] = 0.0
    return out


def drop_snapshots(sysm, keys, reason, sizes=None):
    """Remove these snapshots, except any a hit pinned since they were chosen; each leaves the index before its
    container goes, so a hit never lands on a removed snapshot (lazy_hit pins before it looks)."""
    with TREE.lock:
        keys = [k for k in keys if k not in TREE.pinned]
        gone = [(k, TREE.index.get(k) or {}) for k in keys]
        state = lambda t: "done" if t in TREE.finished else "running" if t in TREE.running else "pending"
    TREE.drop(keys)
    for k, e in gone:
        if "mem" in e:
            sysm.rm([e["mem"]])
            MEM.drop(e["mem"])
        for f in (e.get("obs"), e.get("shot")):
            if f:
                Path(f).unlink(missing_ok=True)
        log("prefix_evict", reason=reason, policy=a.tree_policy, key=k, task=e.get("task"), depth=e.get("depth"),
            hits=e.get("hits", 0), saved_epoch=e.get("epoch"), pss_mib=(sizes or {}).get(k),
            age_s=round(time.time() - e.get("saved_at", time.time()), 1), task_state=state(e.get("task")))


def make_room(sysm, done_only=False):
    """Evict by --tree-policy until one more snapshot fits the budget. done_only: take only snapshots of tasks whose
    group is done this run (a save: next used next epoch). -> False if it can't."""
    with EVICT_LOCK:
        sizes = known_sizes()
        out = TREE.victims(sizes, SNAP_EST_MIB, a.tree_budget_gib * 1024, a.tree_policy, True, roots_last=True,
                           done_only=done_only)
        if out is None:
            return False
        if out:
            drop_snapshots(sysm, out, "budget", sizes)
        return True


def budget_guard(sysm, every=30):
    """A snapshot's PSS grows after it is saved (its lineage goes away): every `every` s, evict while over budget."""
    while not ABORT.is_set():
        time.sleep(every)
        try:
            global SIZES
            SIZES = snapshot_sizes()  # measured outside the lock (seconds); evictions under it
            with EVICT_LOCK:
                sizes = known_sizes()
                out = TREE.victims(sizes, 0, a.tree_budget_gib * 1024, a.tree_policy, True, roots_last=True)
                if out:
                    drop_snapshots(sysm, out, "budget_growth", sizes)
        except Exception as e:
            log("budget_guard_error", error=repr(e)[-300:])


def register_snapshot(k, entry, task, keys, gi, n, t0, benefit_s, step_s=None):
    """benefit_s: desktop time to reach this state from the rollout's start; step_s: of its last step alone (gdsf)."""
    entry = {**entry, "epoch": a.epoch, "task": task["id"], "depth": len(keys), "benefit_s": round(benefit_s, 2),
             "step_s": round(benefit_s if step_s is None else step_s, 2),
             "parent": TREE.key(a.system, task["id"], keys[:-1]) if keys else None}
    TREE.put(k, entry)
    if "mem" in entry:
        MEM.add(entry["mem"], entry["pid"], "cache")
    log("prefix_saved", task=task["id"], g=gi, step=n, secs=round(time.time() - t0, 2), epoch=a.epoch, key=k,
        depth=len(keys), parent=entry["parent"], snapshots=len([e for e in TREE.index.values() if e and "mem" in e]))


def write_reply(k, obs):
    """The tool's reply saved with a snapshot: the tree (json) and the screenshot (png, for screenshot agents)."""
    path = os.path.join(TREE.root, f"{k}.obs.json")
    with open(path, "w") as f:
        json.dump({"accessibility_tree": obs["accessibility_tree"]}, f)
    out = {"obs": path}
    if obs.get("screenshot"):
        out["shot"] = os.path.join(TREE.root, f"{k}.png")
        Path(out["shot"]).write_bytes(obs["screenshot"])
    return out


def read_reply(entry):
    obs = json.load(open(entry["obs"]))
    if entry.get("shot") and os.path.exists(entry["shot"]):
        obs["screenshot"] = Path(entry["shot"]).read_bytes()
    return obs


def tree_save(sysm, task, keys, kid, gi, n, benefit_s=0.0, obs=None, step_s=None):
    """Save the rollout's desktop under `keys` unless too deep, saved, being saved, or refused (parent not cached,
    admission)."""
    k = TREE.claim(a.system, task["id"], keys)
    if not k:
        return
    pk = TREE.key(a.system, task["id"], keys[:-1]) if keys else None  # the parent is a leaf until this registers
    if pk:
        TREE.pin(pk)
    try:
        _tree_save(sysm, task, keys, kid, gi, n, benefit_s, obs, k, step_s)
    finally:
        if pk:
            TREE.unpin(pk)


def _tree_save(sysm, task, keys, kid, gi, n, benefit_s, obs, k, step_s=None):
    if why := TREE.refuse(a.system, task["id"], keys, True, a.tree_admit_visits, benefit_s, a.tree_admit_cost):
        TREE.release(k)
        log("prefix_save_skipped", task=task["id"], g=gi, step=n, reason=why)
        return
    if not make_room(sysm, done_only=True):
        TREE.release(k)  # no finished group's snapshot left to take
        log("prefix_save_skipped", task=task["id"], g=gi, step=n, reason="no_room")
        return
    t0, entry = time.time(), None
    try:
        entry = sysm.snap_mem(kid[0], k)
        if obs is not None and obs.get("accessibility_tree") is not None:
            entry.update(write_reply(k, obs))
        # the parent may still be being saved (a sibling's save, queued for a clone slot): register after it; if it
        # never is, drop this one (no entry without its parent)
        if keys and not TREE.wait_saved(TREE.key(a.system, task["id"], keys[:-1]), a.obs_timeout):
            sysm.rm([entry["mem"]])
            for f in (entry.get("obs"), entry.get("shot")):
                if f:
                    Path(f).unlink(missing_ok=True)
            entry = None
            log("prefix_save_skipped", task=task["id"], g=gi, step=n, reason="parent_not_saved")
            return
        register_snapshot(k, entry, task, keys, gi, n, t0, benefit_s, step_s)
        entry = None  # registered
    except Exception as e:
        log("prefix_save_failed", task=task["id"], g=gi, step=n, error=repr(e)[-300:])
    finally:
        TREE.release(k)


def lazy_hit(task, keys):
    """lazy_entry() with the entry pinned (before the lookup: an eviction in between would leave the rollout on a
    removed snapshot); unpinned again on a miss."""
    k = TREE.key(a.system, task["id"], keys)
    TREE.pin(k)
    e = lazy_entry(task, keys)
    if e is None:
        TREE.unpin(k)
    return e


def lazy_entry(task, keys):
    """The entry for this prefix if it has a saved reply and a live snapshot, else None."""
    e = TREE.get(a.system, task["id"], keys)
    if not e or not e.get("obs") or not os.path.exists(e["obs"]):
        return None
    if "mem" in e and not os.path.exists(f"/proc/{e['pid']}"):
        return None
    return e


def materialize(sysm, task, kid, gi, n, virtual):
    """The rollout is at `virtual`'s snapshot state but its desktop is stale (or absent): fork the snapshot into its
    desktop; rollouts that miss together share one clone. -> env"""
    k, entry, depth = virtual
    t0 = time.time()
    new = sysm.load_shared(entry, f"{kid[0][:24]}-m{n}")  # k stays pinned until this succeeds
    fixup_copies(sysm, [new], task)
    env = adopt(sysm, kid, new, gi, task)
    TREE.unpin(k)
    log("prefix_materialize", task=task["id"], g=gi, step=n, depth=depth, secs=round(time.time() - t0, 2))
    return env


def save_root_reply(task, obs):
    """The first observation after setup is the reply of the task's after-setup snapshot (lets later groups start
    without copies, --tree-lazy-start). Written once, by the first rollout to observe."""
    k = TREE.key(a.system, task["id"], [])
    with TREE.lock:
        e = TREE.index.get(k)
        if not e or e.get("obs") or obs.get("accessibility_tree") is None:
            return
        e.update(write_reply(k, obs))
        TREE._write()


def rollout(task, domain, k, kid, d, sysm=None, gi=None, start=None):
    """kid: [name, addr, pid] of the rollout's desktop; speculation / the prefix cache may swap it (updated in place).
    start: --tree-lazy-start, (key, entry) of the cached after-setup state: no desktop yet (kid's addr is None)."""
    d.mkdir(parents=True, exist_ok=True)
    tm = {"copy": kid[0], "t_start": time.time()}
    env = task_env(kid[1], task) if not start else None
    # --tree-cache: exact keys of the actions so far; each step's desktop time on the path (a hit counts what its step
    # cost when saved: sum = cost from the state after setup, admission); (key, entry, depth) of the deepest hit while
    # the desktop lags behind it
    thist, path_s, virtual = [], [], None
    hist, spec = [], None  # keys of the actions issued so far (the prefix); this step's pending speculation
    retired = []  # desktops this rollout left for a speculative fork: stopped now, removed when the rollout ends
    cached = None  # prefix-cache entry the rollout is virtually at (steps replayed from the cache, desktop not restored yet)
    agent = ReplayAgent(REPLAY / domain / f"{task['id']}__g{k}") if REPLAY else A11yAgent(a.model, temperature=a.temperature)
    agent.reset()
    agent.log = str(d / "chat.jsonl")
    chat_log = None
    if SCACHE:  # a predict may be redone (rejected cached screen): only accepted ones go to chat.jsonl
        chat_log, agent.log = agent.log, None
    pending, sc = None, {"hit": 0, "miss": 0, "reject": 0, "waited_s": 0.0}  # --screen-cache: the background step
    reward, steps, err = 0.0, 0, None
    last_same, run_len = None, 0  # --stop-repeats state
    pre = pre_new = None  # --spec-prefork: last step's copy (one action ahead if its guess hits) / this step's
    recent = []  # --spec-priority: this rollout's step times (model + env)
    prev_slow = False  # --spec-slow: the previous step's env time was >= the run's median env step time
    with LOCK:
        LIVE[0] += 1
        STARTED[0] += 1
    if TREE:
        TREE.visit(a.system, task["id"], [])
    try:
        if start:  # on the cached reply after setup; materialize() forks the desktop at the first miss
            TREE.pin(start[0])
            virtual = (start[0], start[1], 0)
            obs, real_obs = read_reply(start[1]), None
        else:
            obs = real_obs = observe(env)  # real_obs: the real desktop's latest screen (obs may be a cached one)
            if TREE:
                save_root_reply(task, obs)
        for n in range(1, a.max_steps + 1):
            check_abort()
            guesses = []
            if SPEC:
                with SPEC_LOCK:
                    guesses = SPEC.decide(task["id"], str(d))["guesses"]
            pre_new = None
            if (a.spec_prefork and SPEC and BOOK and n >= a.spec_from - 1 and (not a.spec_slow or prev_slow)
                    and STARTED[0] >= TOTAL[0]  # not while groups are still forking their rollout desktops
                    and (not a.spec_priority or straggler(str(d)))
                    and (pending is None or SPEC_AFTER_HIT)  # a served step still running: wait for it (combined only)
                    and not (SPEC_AFTER_HIT and a.spec_tail_live and LIVE[0] > a.spec_tail_live)):
                pre_new = PreFork(sysm, kid, task, gi, f"p{k}x{n}-", after=pending)  # the desktop is idle while the model thinks
            if (a.spec_exec and not a.spec_prefork and guesses and n >= a.spec_from
                    and (not a.spec_below or LIVE[0] < a.spec_below) and (not a.spec_slow or prev_slow)):
                rows_now = linearize(obs["accessibility_tree"])[1]
                spec = (InPlaceSpec(sysm, kid, task, guesses, rows_now, gi, f"s{k}x{n}-", retired) if a.spec_inplace
                        else Speculation(sysm, kid, task, guesses, rows_now, gi, f"s{k}x{n}-"))
            while True:
                seen_text = linearize(obs["accessibility_tree"])[0] if SCACHE else None
                _, codes = agent.predict(task["instruction"], obs)
                if pending is None:
                    break
                ok, real_obs, bg_s, waited = pending.result()  # the previous step's real run, done while this call ran
                pending = None
                sc["waited_s"] += waited
                log("scache_check", task=task["id"], g=gi, k=k, step=n - 1, ok=ok, bg_s=bg_s, waited_s=waited)
                if ok:
                    if real_obs.get("screenshot"):  # what the model saw, as the real desktop shows it
                        (d / f"step_{n - 1}.png").write_bytes(real_obs["screenshot"])
                    break
                sc["reject"] += 1  # the cached screen was wrong: ask again on the real one
                rewind(agent)
                obs = real_obs
            if chat_log:
                append_jsonl(chat_log, agent.last)
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
            pkey = exact_key(act) if TREE and key is not None else None
            if BOOK:
                BOOK.remember(key, act, hit)
            if pre_new is not None:  # action n is known: the copy runs it too, then the guess for n+1
                if key is not None and act.get("action") not in ("done", "fail", "wait"):
                    pre_new.go(real_code(agent, codes, act, rows, real_obs) if SPEC_AFTER_HIT else codes[0], key, hist)
                else:
                    pre_new.drop()
                    pre_new = None
            t0 = time.time()
            took, spec = (spec.finish(key) if spec else None), None
            real_done = None
            if pre is not None:  # last step's copy: it ran action n-1 and guessed this action
                took = (pre.finish(key, rows, env, real_code(agent, codes, act, rows, real_obs) if SPEC_AFTER_HIT else codes[0])
                        if key is not None else (pre.drop() or None))
                if took and took[0] == "real":  # race: the real desktop ran the action first
                    _, env, obs, done = took
                    real_done, took, rec["race"] = True, None, "real"
                if took and pre_new is not None:
                    pre_new.forked.wait()  # it is copying the desktop this hit retires
                pre = None
            if took and took[0] == "switch":  # in-place miss: the desktop is now the clean backup; act on it below
                env, took = took[1], None
            if took and took[0] is None:  # in-place hit: the guess already ran on this very desktop
                _, env, obs, done = took
                rec["skipped"] = "spec"
            elif took:  # a speculative fork already ran this action
                fork, env_new, obs, done = took
                MEM.drop(kid[0])  # stopped, not removed: the adopted fork's rootfs sits on its bundle
                retired.append(kid[0])
                threading.Thread(target=sysm.stop, args=([kid[0]],), daemon=True).start()
                kid[:] = fork
                env, rec["skipped"] = env_new, "spec"
            elif real_done:
                pass  # the race's real-desktop run already took this step
            elif TREE and pkey is not None and (e_ := lazy_hit(task, thist + [pkey])):
                # policy 2 hit (pinned): the saved reply, no desktop work
                if virtual:
                    TREE.unpin(virtual[0])
                virtual = (TREE.key(a.system, task["id"], thist + [pkey]), e_, len(thist) + 1)
                obs, done, rec["skipped"], rec["lazy"] = read_reply(e_), False, "prefix", True
                rec["hit_s"] = e_.get("step_s") or 0.0
                TREE.touch(a.system, task["id"], thist + [pkey], a.epoch)
                log("prefix_hit", task=task["id"], g=gi, step=n, secs=round(time.time() - t0, 3), lazy=True,
                    saved_epoch=e_.get("epoch"), epoch=a.epoch)
            elif TREE:
                if virtual:  # a miss after hits (or the first step of a lazy start): fork the deepest hit, act there
                    env, virtual = materialize(sysm, task, kid, gi, n, virtual), None
                obs, _, done, _ = env.step(codes[0])
                if not done:
                    obs = observe(env, obs)
                    if pkey is not None:
                        tree_save(sysm, task, thist + [pkey], kid, gi, n, sum(path_s) + time.time() - t0, obs,
                                  step_s=time.time() - t0)
            elif SCACHE and key is not None and (e := SCACHE.get(task["id"], seen_text, key)):
                # seen before on this very screen: the model gets the next screen now; the desktop runs it meanwhile
                if pre_new is not None and SPEC_AFTER_HIT:
                    # keep this step's copy: it runs action n itself, then TAGE's guess for n+1 -- unless the cache
                    # already holds (the served next screen, that guess): then the cache will serve step n+1 anyway
                    with SPEC_LOCK:
                        g = SPEC.tage.predict(str(task["id"]), hist + [key])[0]
                    if g and SCACHE.get(task["id"], e[0], g):
                        pre_new.drop()
                        pre_new = None
                elif pre_new is not None:  # this step's speculation copy: the background step takes the action instead
                    pre_new.drop()
                    pre_new = None
                pending = BgStep(env, real_code(agent, codes, act, rows, real_obs), seen_text, e[0], task["id"], key,
                                 wait=pre_new.forked if pre_new is not None else None)
                obs, done, rec["skipped"] = ScreenCache.obs(e), False, "scache"
                sc["hit"] += 1
            elif SCACHE:
                sc["miss"] += 1
                obs, _, done, _ = env.step(real_code(agent, codes, act, rows, real_obs))
                if not done:
                    obs = observe(env, obs)
                    if key is not None:
                        SCACHE.put(task["id"], seen_text, key, obs)
                real_obs = obs
            elif PREFIX and key is not None and (e := PREFIX.get(a.system, task["id"], hist + [key])) and e.get("obs"):
                # this exact path was run before: take its observation from the cache and keep going without
                # touching the desktop; it is restored once, at the first miss or before scoring
                cached, obs, done, rec["skipped"] = e, PREFIX.load_obs(e), False, "prefix"
                log("prefix_hit", task=task["id"], g=gi, step=n)
            else:
                if cached:
                    env, cached = prefix_restore(sysm, cached, task, kid, gi, n), None
                obs, _, done, _ = env.step(codes[0])
                if not done:
                    obs = observe(env, obs)
                    if PREFIX and a.prefix_save and key is not None:
                        prefix_save(sysm, task, hist + [key], kid, gi, n, obs)
            if SCACHE and (rec.get("skipped") == "spec" or real_done):  # speculation ran it on a real desktop
                real_obs = obs
                if key is not None and not done:
                    SCACHE.put(task["id"], seen_text, key, obs)
            if key is not None:
                hist.append(key)
            rec["exec_s"] = round(time.time() - t0, 3)
            if pkey is not None:
                thist.append(pkey)
                TREE.visit(a.system, task["id"], thist)
                path_s.append(rec.get("hit_s", rec["exec_s"]) if rec.get("lazy") else rec["exec_s"])
            tl = agent.last.get("t") or {}
            recent.append(rec["exec_s"] + max(0.0, tl.get("llm_end", 0) - tl.get("llm_start", 0)))
            with LOCK:
                if not (SPEC_AFTER_HIT and rec.get("skipped") == "scache"):  # combined: a served step's ~0 s says nothing
                    ENV_TIMES.append(rec["exec_s"])                         # about the desktop; keep the last real verdict
                    prev_slow = rec["exec_s"] >= statistics.median(ENV_TIMES)
                PROJ[str(d)] = time.time() + (a.max_steps - n) * statistics.mean(recent[-3:])
            if obs.get("screenshot"):
                (d / f"step_{n}.png").write_bytes(obs["screenshot"])
            append_jsonl(d / "traj.jsonl", rec)
            steps = n
            pre = pre_new
            if done:
                break
            # no-progress stop: the same click/type/drag on the same element N times in a row (scrolls and key presses
            # repeat legitimately; invalid actions are not counted)
            same = (act.get("action"), hit and hit["key"], act.get("text")) if act.get("action") in REPEATABLE else None
            run_len = run_len + 1 if same and same == last_same else 1
            last_same = same
            if a.stop_repeats and same and run_len >= a.stop_repeats:
                tm["stopped"] = "repeats"
                log("repeat_stop", task=task["id"], g=gi, k=k, step=n, action=rec["action"])
                break
        if cached:  # the rollout ended inside cached steps: scoring needs the real desktop
            env, cached = prefix_restore(sysm, cached, task, kid, gi, steps), None
        if virtual:  # --tree-cache: ended (done / max steps) on saved replies: the checker needs the real final state
            env, virtual = materialize(sysm, task, kid, gi, steps + 1, virtual), None
        if pending is not None:  # the last step was served from the cache: the desktop must finish it before scoring
            ok, real_obs, bg_s, waited = pending.result()
            pending = None
            log("scache_check", task=task["id"], g=gi, k=k, step=steps, ok=ok, bg_s=bg_s, waited_s=waited, last=True)
        tm["t_eval"] = time.time()
        try:
            reward = evaluate(env)
        except TimeoutError:
            save_eval_evidence(env, d)
            raise
    except Exception as e:
        err = repr(e)
        traceback.print_exc()
    if virtual:
        TREE.unpin(virtual[0])
    if pending is not None:  # an error mid-rollout: let the background step end before the desktop goes
        pending.th.join(timeout=a.obs_timeout)
    if SCACHE:
        tm["scache"] = sc
    if spec:
        spec.finish(None)
    for p in (pre, pre_new):
        if p is not None and not p.adopted:
            p.drop()
    with LOCK:
        PROJ.pop(str(d), None)
    bg_rm(sysm, retired)  # scored: nothing forks this rollout's desktops any more
    with LOCK:
        LIVE[0] -= 1
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
    k0 = cached = e0 = None  # --tree-cache: the key of this task's after-setup state; the cached source, if any
    lazy0 = False  # --tree-lazy-start: that state is cached with its reply: no copies, rollouts start on the reply
    setup_s = 0.0
    if TREE:
        k0 = TREE.key(a.system, tid, [])
        TREE.pin(k0)
        e0 = TREE.get(a.system, tid, [])
        if e0 and "mem" in e0 and os.path.exists(f"/proc/{e0['pid']}"):
            cached = e0["mem"]
            lazy0 = bool(a.tree_lazy_start) and bool(e0.get("obs")) and os.path.exists(e0["obs"])
        with TREE.lock:
            TREE.running.add(tid)
    try:
        with SETUP_SEM:
            check_abort()
            MEM.phase[gi] = "boot"
            if cached:  # fork the rollouts from the cached state after setup: no boot, no setup
                src, (addr, pid) = cached, sysm.info(cached)
                TREE.touch(a.system, tid, [], a.epoch)
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
                # --tree-cache: no cached state after setup -> one more copy, kept idle as that state (the root)
                claim0 = k0 if k0 and not cached and TREE.claim(a.system, tid, []) else None
                if claim0 and not make_room(sysm):
                    TREE.release(claim0)
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
            reward = rollout(task, domain, k, kid, OUT / domain / f"{name}__g{k}", sysm, gi,
                             start=(k0, e0) if lazy0 else None)
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
        sysm.drop_templates(gi)
        # --tree-cache: a cached source stays; a lazy-start placeholder that never got a desktop has no container
        names = ([] if cached else [src]) + [nm for nm, ad, *_ in kids if ad is not None and nm not in released]
        sysm.rm(names)
        for nm in names:
            MEM.drop(nm)
        MEM.phase.pop(gi, None)
        if k0:
            TREE.unpin(k0)
            TREE.release(k0)  # a claim of the after-setup state whose fork failed
        if TREE:
            with TREE.lock:  # its tree's next use is the next epoch: evicted from first
                TREE.running.discard(tid)
                TREE.finished.add(tid)


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
    global MEM, SIZES
    global FORKED, DONE
    batch = json.load(open(CWD / a.tasks))
    tasks = [(dom, t) for dom, ids in batch.items() for t in ids][:a.limit or None]
    if a.shuffle_seed >= 0:
        random.Random(a.shuffle_seed).shuffle(tasks)
    n = a.groups or len(tasks)
    todo = [(*tasks[i % len(tasks)], i // len(tasks)) for i in range(n)]  # (domain, task, repeat)
    if a.prefix_cache and a.prefix_save and a.system in ("tfork", "criu") and a.overlay_rootfs:
        raise SystemExit("saving to --prefix-cache needs --overlay-rootfs 0: an overlay rootfs can't be btrfs-snapshotted "
                         "by the save clone (read-only runs, --prefix-save 0, can keep overlay)")
    if a.sync_groups and a.release_copies:
        raise SystemExit("--release-copies frees copies as rollouts end; --sync-groups holds them all until the end. Pick one.")
    if a.sync_groups:
        FORKED, DONE = Gate(n), Gate(n)
    (OUT / "config.json").write_text(json.dumps(vars(a), indent=1))
    prepare_host(a.system)
    MEM = Mem()
    sysm = Aenv() if a.system == "aenv" else Podman(a.system)
    if TREE:  # snapshots from earlier runs: forget the ones whose container is gone (and what hung below), sample the rest
        with TREE.lock:
            mem = [(k, e) for k, e in TREE.index.items() if e and "mem" in e]
        dead = [k for k, e in mem if not os.path.exists(f"/proc/{e['pid']}")]
        if dead:
            dead = list(TREE.with_descendants(dead))
            drop_snapshots(sysm, dead, "gone")
        for k, e in mem:
            if k not in dead:
                MEM.add(e["mem"], e["pid"], "cache")
        SIZES = snapshot_sizes()
        log("prefix_mem_start", snapshots=len(mem) - len(dead), gone=len(dead), budget_gib=a.tree_budget_gib,
            policy=a.tree_policy, dir=TREE.root)
        threading.Thread(target=budget_guard, args=(sysm,), daemon=True).start()
    if PREFIX and a.prefix_clear:
        snaps = PREFIX.clear()
        if a.system != "aenv":  # tfork / CKPT entries are stopped clones; rm reaps their bundle and image
            sysm.rm(snaps)
            snaps = []
        log("prefix_cleared", dir=PREFIX.root, aenv_snapshots_left=snaps)  # aenv has no snapshot delete command
    if SPEC and a.spec_warm:  # earlier epochs: TAGE learns their actions, the book how to perform them
        dirs = [str((CWD / x).resolve()) for x in a.spec_warm.split(",")]
        n = SPEC.warm(dirs)
        for p in (glob.glob(f"{x}/**/traj.jsonl", recursive=True) for x in dirs) if BOOK else []:
            for f in p:
                for s in (json.loads(l) for l in open(f) if l.strip()):
                    if "action_timestamp" in s:
                        act, hit = json.loads(s["action"]), s.get("a11y_hit")
                        BOOK.remember(action_key(act, hit), act, hit)
        log("spec_warm", dirs=dirs, reveals=n, book=len(BOOK.acts) if BOOK else 0)
    if TREE:
        if SPEC or PREFIX or SCACHE or a.system != "tfork":
            raise SystemExit("--tree-cache (policy 2) runs alone, on tfork (no --spec / --prefix-cache / --screen-cache)")
        if a.overlay_rootfs:
            raise SystemExit("--tree-cache: use --overlay-rootfs 0 (its tested setting; snapshots are clones of copies)")
        TREE.schedule = {tid: i for i, (_, tid, _) in reversed(list(enumerate(todo)))}
    if SCACHE:
        if PREFIX or (SPEC and not (a.spec_prefork and a.spec_exec)):
            raise SystemExit("--screen-cache: no --prefix-cache; with --spec only the pre-fork mode (--spec-prefork 1 --spec-exec 1)")
        dirs = [str((CWD / x).resolve()) for x in a.screen_warm.split(",") if x]
        log("screen_warm", dirs=dirs, entries=SCACHE.warm(dirs))
    TOTAL[0] = len(todo) * a.rollouts
    log("run_start", system=a.system, spec=a.spec, tasks=len(todo), rollouts=a.rollouts, host_baseline=MEM.snapshot()["host"])
    base = base_fork(sysm, len(todo)) if a.base_fork else None
    try:
        with ThreadPoolExecutor(len(todo) if a.sync_groups else a.parallel or len(todo)) as ex:
            list(ex.map(lambda x: group(sysm, x[0], *x[1]), enumerate(todo)))
    finally:
        for t in BG_RM + BG_SAVES:  # adopt()'s background removals; saves still finishing their dumps (epoch boundary)
            t.join()
        if base:
            sysm.rm([base])
            MEM.drop(base)
    if SPEC:
        (OUT / "spec_summary.json").write_text(json.dumps(SPEC.summary(), indent=1))
    if TREE:
        TREE.save_visits()
    log("run_done", aborted=ABORT.is_set())


if __name__ == "__main__":
    main()
