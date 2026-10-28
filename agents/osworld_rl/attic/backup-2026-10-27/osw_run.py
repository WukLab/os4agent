"""OSWorld GRPO rollouts on forked desktops, with memory/CPU profiling.   Runs as root on the env host (06).
  sudo env DOUBAO_API_URL=http://127.0.0.1:8100/v1 venv/bin/python osw_run.py --system criu --result-dir traces/<run> [--spec tage]
Per task (one group at a time): boot ONE source desktop (KDE webtop + OSWorld server, started by desk_osw.sh, the same way on every
system) -> OSWorld's own task setup on it (DesktopEnv.reset) -> fork it into G copies (stock CRIU: checkpoint --leave-running + G
restores; tfork: one live clone of G copies) -> G rollouts in parallel with the a11y agent -> OSWorld's own evaluator on each copy.
--spec tage: the toolspec TAGE predictor (../toolspec) guesses each step's action before the LLM call; shadow only (logged, never run).
Writes <result-dir>/:
  mem.jsonl     every --sample-s: host memory + CPU, per-container smaps (PSS/anon/file/shmem) of the source and every copy, phase
  events.jsonl  boot / setup / fork (checkpoint + each restore, image size) / rollouts, with a full memory snapshot before and after fork
  <domain>/<task>__g<k>/  chat.jsonl (GRPO input), result.txt, traj.jsonl (+ "spec"), step_<n>.png, timing.json
  spec_summary.json (--spec tage)"""
import argparse, glob, json, os, re, shutil, shlex, subprocess, sys, threading, time, traceback, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import resource
# AENV mode holds 4 forwarding listeners + their connections per sandbox (~260 sandboxes); the default soft limit of 1024 runs out.
resource.setrlimit(resource.RLIMIT_NOFILE, (resource.getrlimit(resource.RLIMIT_NOFILE)[1],) * 2)

HERE = Path(__file__).resolve().parent
OSW = HERE / "OSWorld"
sys.path[:0] = [str(OSW), str(HERE)]
os.chdir(OSW)  # OSWorld resolves its cache dir relative to cwd

ap = argparse.ArgumentParser()
ap.add_argument("--system", choices=["tfork", "criu", "stock-criu", "aenv"], required=True,
                help="tfork: one live clone of N copies (--persistent=async). criu: N serial single-copy clones with "
                     "--persistent=sync = full CRIU dump + restore per copy, our CRIU (agents/agent-s CKPT mode). stock-criu: distro "
                     "runc + /usr/sbin/criu checkpoint/restore (drops memory protection keys -> needs slirp + no-pkey seccomp). "
                     "aenv: AgentENV microVM sandboxes, fork API (needs io_uring on + aenv-server)")
ap.add_argument("--aenv-template", default="kde-osworld"); ap.add_argument("--aenv-cli", default="/home/vikranth/.local/bin/aenv")
ap.add_argument("--aenv-home", default="/home/vikranth", help="HOME for the aenv CLI (its credentials file)")
ap.add_argument("--tasks", default=str(HERE / "grpo_batch.json")); ap.add_argument("--result-dir", required=True)
ap.add_argument("--rollouts", type=int, default=8); ap.add_argument("--max-steps", type=int, default=15)
ap.add_argument("--model", default=os.environ.get("SERVED", "qwen3vl8b")); ap.add_argument("--temperature", type=float, default=1.0)
ap.add_argument("--replay", default="", help="trace dir of an earlier run: each rollout <domain>/<task>__g<k> re-executes that recorded "
                "rollout's actions (no model calls); targets are re-found by role+name in the current a11y tree")
ap.add_argument("--replay-latency", type=float, default=1.0, help="replay: sleep this x the recorded LLM latency per step (0 = none)")
ap.add_argument("--spec", choices=["off", "tage"], default=os.environ.get("SPEC", "off")); ap.add_argument("--spec-topk", type=int, default=8)
ap.add_argument("--image", default="ghcr.io/wuklab/webtop:ubuntu-kde-osworld")
ap.add_argument("--os4agent", default="/mnt/ssd2/os4agent"); ap.add_argument("--storage-conf", default="/mnt/btrfs/podman/storage.conf")
ap.add_argument("--net", choices=["auto", "slirp", "bridge"], default="auto",
                help="auto: bridge, except slirp for stock-criu (stock CRIU can't re-bind Chromium's connected UDP DNS sockets to a "
                     "copy's new IP; with slirp every copy keeps the in-container IP 10.0.2.100)")
ap.add_argument("--seccomp", default="auto",
                help="auto: unconfined, except stock-criu gets seccomp_nopkey.json (stock CRIU drops memory protection keys and "
                     "restored Chromium renderers then crash with SIGTRAP; blocking pkey_alloc makes Chromium not use them)")
ap.add_argument("--full-memcopy", type=int, default=1,
                help="criu (CKPT): 1 = --tfork-full-memcopy, every copy gets private anon memory like a classic restore (no CoW with "
                     "the source); 0 = our CRIU's restore maps anon pages CoW from the source")
ap.add_argument("--save-ckpt", default="", help="criu: keep each task group's CRIU memory image (copy 0's dump of the source) under "
                "<dir>/<run>/<domain>/<task>/ (btrfs reflink copy of the clone's tfork bundle img/)")
ap.add_argument("--parallel", type=int, default=1, help="task groups run at once (0 = all)")
ap.add_argument("--fork-concurrency", type=int, default=4,
                help="task groups forking at the same time (all groups still run concurrently afterwards). Unbounded parallel forks "
                     "of 32 groups make restores miss tfork's fixed 10 s restore wait and race Thunderbird's netlink socket")
ap.add_argument("--overlay-rootfs", type=int, default=1, help="tfork: --tfork-overlay-btrfs (copies share one read-only rootfs and its "
                "page cache). Off = a btrfs snapshot per copy: 8 copies re-read every binary from disk at restore, and concurrent forks then "
                "exceed CRIU's 10 s restore-stage wait")
ap.add_argument("--base-fork", type=int, default=0, help="boot ONE desktop, fork it into every task group's source (sources share "
                "the base desktop's pages), then setup + rollout forks as usual (two-level fork tree)")
ap.add_argument("--sample-s", type=float, default=2.0); ap.add_argument("--limit", type=int, default=0, help="first N tasks only")
a = ap.parse_args()

from desktop_env import desktop_env as dem
from desktop_env.desktop_env import DesktopEnv
from a11y_owl_agent import A11yAgent, linearize, to_code
from toolspec.online import OnlineTage

OUT = Path(a.result_dir) if os.path.isabs(a.result_dir) else Path(os.environ.get("PWD", HERE)) / a.result_dir   # cwd is OSWorld/ by now
OUT = OUT.resolve(); OUT.mkdir(parents=True, exist_ok=True)
REPLAY = (Path(os.environ.get("PWD", HERE)) / a.replay).resolve() if a.replay else None   # same cwd caveat as OUT
DESK = (Path(a.os4agent) / "agents/osworld_rl/desk_osw.sh").read_text()
RUN = OUT.name.replace("_", "-")[:40]
SPEC = OnlineTage(a.spec_topk) if a.spec == "tage" else None
LOCK = threading.Lock()
FORK_SEM = threading.Semaphore(a.fork_concurrency)


def log(ev, **kw):
    rec = {"t": time.time(), "event": ev, **kw}
    print(json.dumps(rec)[:400], flush=True)
    with LOCK, open(OUT / "events.jsonl", "a") as f: f.write(json.dumps(rec) + "\n")


def sh(argv, check=True, timeout=900, **kw):
    r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, **kw)
    if check and r.returncode:
        out = (r.stderr or r.stdout).replace("\\n", "\n")
        errs = "\n".join(l.strip()[:300] for l in out.splitlines() if "Error (" in l)[:4000]   # every CRIU error line, not just the tail
        raise RuntimeError(f"{' '.join(argv[:6])}... rc={r.returncode}: {errs or out[-1500:]}")
    return r


# ---------------------------------------------------------------- memory

SMAPS = ("Rss", "Pss", "Pss_Anon", "Pss_File", "Pss_Shmem")


def meminfo():
    return {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}


def pidns_pids():
    """pid namespace inode -> [pids], one /proc walk for all containers."""
    out = {}
    for p in os.listdir("/proc"):
        if p.isdigit():
            try: out.setdefault(os.readlink(f"/proc/{p}/ns/pid"), []).append(int(p))
            except OSError: pass
    return out


def smaps(pids):
    tot = dict.fromkeys(SMAPS, 0); n = 0
    for pid in pids:
        try:
            for line in open(f"/proc/{pid}/smaps_rollup"):
                k, _, v = line.partition(":")
                if k in tot: tot[k] += int(v.split()[0])
            n += 1
        except (OSError, ValueError): continue
    return {**{k.lower() + "_mib": round(v / 1024, 1) for k, v in tot.items()}, "nprocs": n}


CG_KEYS = ("anon", "file", "shmem", "kernel")


def cgroup_mem(pid):
    """the container cgroup's own charge: memory.current + memory.stat breakdown (MiB). Unlike PSS this includes unmapped tmpfs
    (/config, /tmp, /dev/shm), unmapped page cache and kernel memory; each page is charged to exactly one cgroup (with CoW the
    shared pages stay charged to the cgroup that first allocated them, so per-container values only sum correctly in total)."""
    rel = open(f"/proc/{pid}/cgroup").read().strip().split("::", 1)[1]
    d = f"/sys/fs/cgroup{rel}"
    st = {l.split()[0]: int(l.split()[1]) for l in open(f"{d}/memory.stat")}
    return {"cg_mib": round(int(open(f"{d}/memory.current").read()) / 2**20, 1), **{f"cg_{k}_mib": round(st.get(k, 0) / 2**20, 1) for k in CG_KEYS}}


class Mem:
    """Live environments (name -> container init pid, or ("vm", firecracker pid) for AENV) + a sampler thread writing mem.jsonl."""
    def __init__(self):
        self.ctr, self.owner, self.phase, self.cpu0 = {}, {}, {}, self._cpu()   # name -> pid; name -> task index; task index -> phase
        m = meminfo(); self.base_used = (m["MemTotal"] - m["MemAvailable"]) // 1024   # host is shared: report deltas from this
        threading.Thread(target=self._loop, daemon=True).start()

    @staticmethod
    def _cpu():
        v = list(map(int, open("/proc/stat").readline().split()[1:])); return v[0] + v[1], v[2], v[4], sum(v)

    def add(self, name, pid, ti): self.ctr[name] = pid; self.owner[name] = ti

    def drop(self, name): self.ctr.pop(name, None); self.owner.pop(name, None)

    def snapshot(self, ti=None):
        """all environments, or only task group ti's (per-group events while groups run in parallel)."""
        ns = pidns_pids(); m = meminfo(); per = {}
        for name, pid in list(self.ctr.items()):
            if ti is not None and self.owner.get(name) != ti: continue
            try:
                if isinstance(pid, tuple): per[name] = smaps([pid[1]])   # AENV: the sandbox's VMM process holds the guest RAM
                else: per[name] = {**smaps(ns.get(os.readlink(f"/proc/{pid}/ns/pid"), [])), **cgroup_mem(pid)}
                per[name]["t"] = self.owner.get(name)
            except OSError: pass
        tot = {k: round(sum(c.get(k, 0) for c in per.values()), 1)
               for k in ("pss_mib", "pss_anon_mib", "pss_file_mib", "pss_shmem_mib", "rss_mib", "cg_mib", *(f"cg_{x}_mib" for x in CG_KEYS))}
        host = {"used_mib": (m["MemTotal"] - m["MemAvailable"]) // 1024, "avail_mib": m["MemAvailable"] // 1024,
                "used_delta_mib": (m["MemTotal"] - m["MemAvailable"]) // 1024 - self.base_used,   # vs. idle host at run start
                "anon_mib": m["AnonPages"] // 1024, "shmem_mib": m["Shmem"] // 1024, "cached_mib": m["Cached"] // 1024}
        return {"containers": per, "total": tot, "host": host}

    def _loop(self):
        while True:
            time.sleep(a.sample_s)
            try:
                c = self._cpu(); d = [x - y for x, y in zip(c, self.cpu0)]; self.cpu0 = c; t = d[3] or 1
                s = self.snapshot()
                rec = {"t": time.time(), "phases": dict(self.phase), "cpu": {"user": round(d[0] / t, 4), "sys": round(d[1] / t, 4), "iowait": round(d[2] / t, 4)},
                       "load1": os.getloadavg()[0], **s}
                with LOCK, open(OUT / "mem.jsonl", "a") as f: f.write(json.dumps(rec) + "\n")
            except Exception as e:
                print("sampler:", e, flush=True)


MEM = None


# ---------------------------------------------------------------- systems (podman: tfork or stock CRIU)

PORTS = ("5000", "9222", "8006", "8080")   # OSWorld server, chromium CDP, vnc, vlc


def tfork_failure(stderr):
    """CRIU error lines from a failed clone's crun-tfork.log (only present when the bundle was kept), then remove that bundle."""
    m = re.search(r"(/[^\s\"]*/tfork-bundles/[0-9a-f]+)/crun-tfork\.log", stderr or "")
    if not m or not os.path.exists(m.group(1) + "/crun-tfork.log"): return (stderr or "")[-300:]
    b = m.group(1)
    errs = [l.strip()[:220] for l in open(b + "/crun-tfork.log", errors="replace") if "Error" in l]
    keep = OUT / "failed_clones" / os.path.basename(b)[:16]; keep.mkdir(parents=True, exist_ok=True)   # the bundle is deleted below
    for f in [b + "/crun-tfork.log", *glob.glob(b + "/img/tfork*.log*")]:
        shutil.copy(f, keep)
        if "restore" in f: errs += [f"{os.path.basename(f)}: {l.strip()[:200]}" for l in open(f, errors="replace") if "Error" in l][:4]
    for mnt in sorted((l.split()[1] for l in open("/proc/mounts") if l.split()[1].startswith(b + "/")), reverse=True):
        subprocess.run(["umount", "-l", mnt], check=False)
    if os.path.isdir(b + "/snap-ro"): subprocess.run(["btrfs", "subvolume", "delete", b + "/snap-ro"], capture_output=True)
    subprocess.run(["rm", "-rf", b], check=False)
    return errs[:12]


def ids(stdout):
    """container IDs printed by `podman container clone` (one 64-hex id per line)."""
    return [l.strip() for l in stdout.splitlines() if len(l.strip()) == 64]


class Podman:
    def __init__(self, system):
        self.system = system
        # fixed copy of the containers.conf podman-tfork.sh generates: without CONTAINERS_CONF the wrapper rewrites that file on every
        # call, and with task groups cloning in parallel another call can read it half-written ("OCI Runtime crun ... not available")
        self.env = {**os.environ, "CONTAINERS_STORAGE_CONF": a.storage_conf, "CONTAINERS_CONF": str(HERE / "containers-os4agent.conf")}
        if system == "stock-criu": self.env["OS4AGENT_CRIU_DIR"] = "/usr/sbin"   # distro criu instead of ours
        self.bin = [str(Path(a.os4agent) / "podman-tfork.sh")]

    def p(self, *args, check=True, timeout=900):
        return sh([*self.bin, *args], check=check, timeout=timeout, env=self.env)

    def slirp(self): return a.net == "slirp" or (a.net == "auto" and self.system == "stock-criu")

    def seccomp(self):
        if a.seccomp != "auto": return a.seccomp
        return str(HERE / "seccomp_nopkey.json") if self.system == "stock-criu" else "unconfined"

    def info(self, name):
        """-> (addr "host:server:chromium:vnc:vlc", init pid)."""
        r = json.loads(self.p("inspect", name).stdout)[0]; pid = r["State"]["Pid"]
        if not self.slirp(): return f"{r['NetworkSettings']['IPAddress']}:5000:9222:8006:8080", pid
        ports = r["NetworkSettings"]["Ports"]
        return "127.0.0.1:" + ":".join(ports[f"{p}/tcp"][0]["HostPort"] for p in PORTS), pid

    def start_source(self, name):
        extra = []
        # --cgroupns=host: without it restores fail with "cg: cgroupd: recv req error" (agents/agent-s/drivers/podman.py)
        # high nofile: the kernel caps a user's in-flight SCM_RIGHTS fds at the sender's RLIMIT_NOFILE. All copies run as the same
        # uid, so with copies alive (CKPT's serial dumps) Chromium's in-flight IPC fds exceed 1024 and CRIU's parasite send_fds
        # fails with ETOOMANYREFS. Same limit for every system.
        extra = ["--cgroupns=host", "--ulimit", "nofile=1048576:1048576"]
        if self.system == "stock-criu":   # CRIU options (ghost-limit, tcp-close, link-remap, file-locks) for runc checkpoint/restore
            extra += ["--runtime", "/usr/sbin/runc", "--annotation", f"org.criu.config={a.os4agent}/agents/agent-s/drivers/criu-baseline.conf"]
        if self.slirp(): extra += ["--network", "slirp4netns:port_handler=slirp4netns", *[x for p in PORTS for x in ("-p", p)]]
        self.p("rm", "-f", name, check=False)
        self.p("run", "-d", "--name", name, *extra, "--security-opt", f"seccomp={self.seccomp()}", "--security-opt", "label=disable",
               "--shm-size=2g", "--tmpfs", "/config:size=4g", "--tmpfs", "/tmp:size=1g", "--tmpfs", "/run:size=256m",
               "--entrypoint", "bash", a.image, "-c", DESK)
        return name, *self.info(name)

    def fork(self, src, n, task, on_copy=lambda *_: None):
        """-> [(name, addr, pid)]; logs timings; on_copy(name, addr, pid) as soon as each copy exists (memory tracking)."""
        ghost = f"--tfork-ghost-limit={64 << 20}"
        if self.system in ("tfork", "criu"):
            self.p("exec", src, "true"); time.sleep(0.1)   # let tini reap exec children before the freeze (agents/gta bench)
        if self.system == "tfork":   # one live clone, N copies; memory image persisted in the background
            for attempt in range(5):
                if attempt: time.sleep(20 * attempt)   # same backoff as CKPT
                t0 = time.time()
                env = {**self.env, **({"PODMAN_TFORK_NO_REAP": "1"} if attempt else {})}
                r = sh([*self.bin, "container", "clone", "--live", f"--copies={n}", "--persistent=async", "--tfork-tcp-close", ghost,
                        *(["--tfork-overlay-btrfs"] if a.overlay_rootfs else []),
                        "--name", f"{src}-k", src], check=False, timeout=900, env=env)
                log("tfork_clone", task=task, attempt=attempt, ok=r.returncode == 0, secs=round(time.time() - t0, 3),
                    why=tfork_failure(r.stderr) if r.returncode else "")
                if r.returncode == 0: break
            else: raise RuntimeError("tfork clone failed 5x")
            names = ids(r.stdout)
        elif self.system == "criu":   # CKPT: N serial single-copy clones, each a synchronous full dump + restore
            names = []
            for i in range(n):
                for attempt in range(5):   # retries keep the failed bundle (PODMAN_TFORK_NO_REAP) so crun-tfork.log can be read
                    if attempt: time.sleep(20 * attempt)   # e.g. "netlink: The socket has data to read": give the process time to drain it
                    t0 = time.time()
                    env = {**self.env, **({"PODMAN_TFORK_NO_REAP": "1"} if attempt else {})}
                    r = sh([*self.bin, "container", "clone", "--live", "--copies=1", "--persistent=sync", "--tfork-tcp-close", ghost,
                            *(["--tfork-full-memcopy"] if a.full_memcopy else []), "--name", f"{src}-k{i}", src],
                           check=False, timeout=900, env=env)
                    if r.returncode == 0: break
                    log("ckpt_clone_failed", task=task, copy=i, attempt=attempt, secs=round(time.time() - t0, 3), why=tfork_failure(r.stderr))
                else: raise RuntimeError(f"CKPT clone {i} failed 5x")
                names += ids(r.stdout); log("ckpt_clone", task=task, copy=i, attempt=attempt, secs=round(time.time() - t0, 3))
                on_copy(names[-1], *self.info(names[-1]))
        else:
            tar = Path(f"/mnt/btrfs/criu-{src}.tar")
            try:
                t0 = time.time()
                self.p("container", "checkpoint", "--leave-running", "--tcp-established", "--compress=none", f"--export={tar}", src)
                log("criu_checkpoint", task=task, secs=round(time.time() - t0, 3), image_mib=round(tar.stat().st_size / 2**20, 1))
                names = []
                for i in range(n):
                    t1 = time.time()
                    pub = [x for p in PORTS for x in ("--publish", p)] if self.slirp() else []   # fresh random host ports per copy
                    self.p("container", "restore", f"--import={tar}", "--name", f"{src}-k-{i}", "--ignore-static-ip", "--ignore-static-mac", *pub)
                    log("criu_restore", task=task, copy=i, secs=round(time.time() - t1, 3)); names.append(f"{src}-k-{i}")
            finally:
                tar.unlink(missing_ok=True)
        return [(nm, *self.info(nm)) for nm in names]

    def run_in(self, name, cmd): return self.p("exec", name, "bash", "-c", cmd, check=False, timeout=60)

    def save_checkpoint(self, clone, dest, task):
        """copy a CKPT clone's persisted CRIU image (tfork bundle img/) to dest; reflink, so ~free until the bundle is removed."""
        ann = json.loads(self.p("inspect", clone).stdout)[0]["Config"]["Annotations"]
        img = Path(f"{Path(a.storage_conf).parent}/storage/tfork-bundles/{ann['io.podman.tfork.batch-id']}/img")
        dest.parent.mkdir(parents=True, exist_ok=True); t0 = time.time()
        sh(["cp", "-a", "--reflink=auto", str(img), str(dest)])
        mib = int(sh(["du", "-sm", str(dest)]).stdout.split()[0])
        log("checkpoint_saved", task=task, path=str(dest), mib=mib, secs=round(time.time() - t0, 2))

    def rm(self, names):
        if names: self.p("rm", "-f", *names, check=False, timeout=300)


# ---------------------------------------------------------------- AENV (Firecracker microVM sandboxes)

def setns_net(pid):
    """move the CALLING THREAD into pid's network namespace (sockets it creates afterwards live there)."""
    import ctypes
    with open(f"/proc/{pid}/ns/net") as f:
        if ctypes.CDLL(None, use_errno=True).setns(f.fileno(), 0x40000000) != 0: raise OSError(ctypes.get_errno(), "setns")


class Forwarder:
    """127.0.0.1:<random> -> one sandbox port, as a plain TCP relay straight to the VM: AENV routes every VM slot's address
    (10.11.0.N) inside the aenv-server container's network namespace, which is what its HTTP proxy connects to. Going direct keeps the
    path the same as for containers (runner -> server, only OSWorld's own 60 s request timeout): AENV's proxy cuts any request at 30 s
    (504), which the LibreOffice a11y tree exceeds under load. A plain relay also keeps Host as sent, so Chrome's CDP ws:// URLs work."""
    def __init__(self, netns_pid, ip, port):
        import socket
        self.ns, self.up = netns_pid, (ip, int(port))
        self.ls = socket.socket(); self.ls.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ls.bind(("127.0.0.1", 0)); self.ls.listen(256); self.local = self.ls.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try: c, _ = self.ls.accept()
            except OSError: return
            threading.Thread(target=self._conn, args=(c,), daemon=True).start()

    def _conn(self, c):
        import socket
        try:
            setns_net(self.ns); u = socket.create_connection(self.up)   # this thread only; c stays in the host namespace
        except OSError:
            c.close(); return
        def pipe(s, d):
            try:
                while (x := s.recv(65536)): d.sendall(x)
            except OSError: pass
            finally:
                for z in (s, d):
                    try: z.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
        threading.Thread(target=pipe, args=(u, c), daemon=True).start(); pipe(c, u)

    def close(self): self.ls.close()


class Aenv:
    """AENV sandboxes. Needs io_uring enabled (kernel.io_uring_disabled=0) and the aenv-server container up; tfork/CRIU need it
    disabled, so systems run one at a time. Template: built from the same image (see AENV_TEMPLATE / --aenv-template)."""
    URL = "http://127.0.0.1:8000"

    def __init__(self):
        self.key = Path("/mnt/ssd2/aenv/env/secrets/api-key").read_text().strip()
        self.cli = [a.aenv_cli]; self.env = {**os.environ, "HOME": a.aenv_home}   # the CLI reads <HOME>/.config/aenv/credentials
        self.fw, self.pid, self.owned, self.lock = {}, {}, set(), threading.Lock()   # sandbox -> [Forwarder] / VMM pid
        self.ip = {}   # sandbox -> its VM slot address inside aenv-server's netns
        self.srv = int(sh(["docker", "inspect", "aenv-server", "--format", "{{.State.Pid}}"]).stdout)

    def api(self, method, path, body=None, timeout=600):
        req = urllib.request.Request(self.URL + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-API-Key": self.key, "Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")

    def a(self, *args, check=True, timeout=900): return sh([*self.cli, *args], check=check, timeout=timeout, env=self.env)

    @staticmethod
    def active_vmms():
        """Firecracker processes serving a sandbox. AENV pre-spawns a pool of VMMs with random work dirs and nothing names the
        sandbox, but a VMM opens the sandbox's ublk block devices when it is assigned one."""
        out = set()
        for p in os.listdir("/proc"):
            if not p.isdigit(): continue
            try:
                if not open(f"/proc/{p}/comm").read().startswith("firecracker"): continue
                if any(os.readlink(f"/proc/{p}/fd/{fd}").startswith("/dev/ublkb") for fd in os.listdir(f"/proc/{p}/fd")): out.add(int(p))
            except OSError: continue
        return out

    def claim(self, before, n, timeout=60):
        """the n VMMs that became active since `before` (call under self.lock so no other start/fork interleaves)."""
        t0 = time.time(); new = []
        while time.time() - t0 < timeout:
            new = sorted(self.active_vmms() - before - self.owned)
            if len(new) >= n: self.owned.update(new[:n]); return new[:n]
            time.sleep(0.2)
        raise RuntimeError(f"expected {n} new firecracker VMMs, found {len(new)}")

    def slot_ip(self, vmm):
        """VMM pid -> its slot address: the VMM netns' vpeer address is the next hop of exactly one 10.11.x.y route in aenv-server."""
        vpeer = sh(["nsenter", "-t", str(vmm), "-n", "ip", "-4", "-o", "addr", "show", "dev", "vpeer"]).stdout.split()[3].split("/")[0]
        for l in sh(["nsenter", "-t", str(self.srv), "-n", "ip", "-4", "route"]).stdout.splitlines():
            f = l.split()
            if len(f) >= 3 and f[1] == "via" and f[2] == vpeer: return f[0]
        raise RuntimeError(f"no aenv route via {vpeer} (vmm {vmm})")

    def whoami(self, ip, timeout=30):
        """read /tmp/.aenv_sandbox_id over the direct path (server /execute), so forked copies are paired with their own VM."""
        import socket
        def get(res):
            try:
                setns_net(self.srv)
                req = urllib.request.Request(f"http://{ip}:5000/execute", data=json.dumps({"command": "cat /tmp/.aenv_sandbox_id", "shell": True}).encode(),
                                             headers={"Content-Type": "application/json"})
                res.append(json.loads(urllib.request.urlopen(req, timeout=timeout).read()).get("output", "").strip())
            except Exception: res.append("")
        res = []; t = threading.Thread(target=get, args=(res,)); t.start(); t.join(); return res[0]

    def info(self, sb):
        fws = self.fw.setdefault(sb, [Forwarder(self.srv, self.ip[sb], p) for p in PORTS])
        return "127.0.0.1:" + ":".join(str(f.local) for f in fws), ("vm", self.pid[sb])

    def start_source(self, name):
        with self.lock:
            before = self.active_vmms()
            sb = self.a("start", a.aenv_template, "--detach", "--timeout", "7200").stdout.split()[-1]
            self.pid[sb] = self.claim(before, 1)[0]
        self.ip[sb] = self.slot_ip(self.pid[sb])
        self.a("upload", sb, str(Path(a.os4agent) / "agents/osworld_rl/desk_osw.sh"), "/tmp/desk_osw.sh")
        self.a("exec", sb, "--", "bash", "-c", "setsid nohup bash /tmp/desk_osw.sh >/dev/null 2>&1 < /dev/null &")
        return sb, *self.info(sb)

    def fork(self, src, n, task, on_copy=None):
        with self.lock:
            before = self.active_vmms(); t0 = time.time()
            res = self.api("POST", f"/sandboxes/{src}/fork", {"count": n, "timeout": 7200})
            errs = [e.get("error") for e in res if "sandbox" not in e]
            if errs: raise RuntimeError(f"aenv fork errors: {errs}")
            kids = [e["sandbox"]["sandboxID"] for e in res]; vmms = self.claim(before, len(kids)); fork_s = time.time() - t0
        t1 = time.time()   # pairing is runner plumbing, logged apart from the fork itself
        # pair each copy with its own VM: tag it through AENV's exec channel, then read the tag back over each VM's direct address
        for k in kids: self.a("exec", k, "--", "sh", "-c", f"echo {k} > /tmp/.aenv_sandbox_id", timeout=120)
        by_ip = {self.slot_ip(v): v for v in vmms}
        for ip, v in by_ip.items():
            for _ in range(6):   # a just-resumed VM's server can be slow to answer under load
                if (k := self.whoami(ip)) in kids: break
                time.sleep(10)
            if k not in kids: raise RuntimeError(f"aenv fork: VM {ip} answered {k!r}, not one of this fork's copies")
            self.pid[k], self.ip[k] = v, ip
        if len({self.ip.get(k) for k in kids}) != len(kids): raise RuntimeError("aenv fork: copies and VMs did not pair 1:1")
        log("aenv_fork", task=task, copies=len(kids), secs=round(fork_s, 3), pair_secs=round(time.time() - t1, 3))
        return [(k, *self.info(k)) for k in kids]

    def run_in(self, name, cmd): return self.a("exec", name, "--", "bash", "-c", cmd, check=False, timeout=60)

    def rm(self, names):
        for n in names:
            for f in self.fw.pop(n, []): f.close()
            self.owned.discard(self.pid.pop(n, None))
            self.a("rm", n, check=False, timeout=120)


def prepare_host(system):
    """Put the host in the mode the system needs: AENV's ublk storage needs io_uring and its server container; tfork/CRIU need
    io_uring disabled (kernel.io_uring_disabled=2), so the AENV server is stopped first (its sandboxes cannot run without io_uring)."""
    def aenv_up():
        try: return urllib.request.urlopen(Aenv.URL + "/health", timeout=3).status in (200, 204)
        except Exception: return False
    if system == "aenv":
        open("/proc/sys/kernel/io_uring_disabled", "w").write("0\n")
        if not aenv_up():
            sh(["docker", "start", "aenv-server"])
            for _ in range(90):
                if aenv_up(): break
                time.sleep(2)
            else: raise SystemExit("aenv-server did not become healthy")
    else:
        if sh(["docker", "ps", "-q", "-f", "name=^aenv-server$"]).stdout.strip(): sh(["docker", "stop", "aenv-server"], timeout=300)
        open("/proc/sys/kernel/io_uring_disabled", "w").write("2\n")
    log("host_mode", system=system, io_uring_disabled=int(open("/proc/sys/kernel/io_uring_disabled").read()), aenv_server=aenv_up())


# ---------------------------------------------------------------- OSWorld plumbing

class FixedProvider:
    """OSWorld provider for a desktop that already runs: just its address "host:server:chromium:vnc:vlc"."""
    def __init__(self, addr): self.addr = addr
    def start_emulator(self, *_a, **_k): pass
    def get_ip_address(self, *_a, **_k): return self.addr
    def stop_emulator(self, *_a, **_k): pass
    def revert_to_snapshot(self, *_a, **_k): raise RuntimeError("forked copies are never reverted")
    def save_state(self, *_a, **_k): pass


class _Mgr:
    def get_vm_path(self, *_a, **_k): return "external"


ENV_LOCK, SPEC_LOCK = threading.Lock(), threading.Lock()


def make_env(ip):
    with ENV_LOCK:   # the provider factory is module-global; rollout threads build envs concurrently
        dem.create_vm_manager_and_provider = lambda *_a, **_k: (_Mgr(), FixedProvider(ip))
        return DesktopEnv(provider_name="docker", path_to_vm=f"external-{ip}", action_space="pyautogui", require_a11y_tree=True,
                      headless=True, recording_update="off")


def http_ok(addr, path="screenshot", t=10):
    host, port = addr.split(":")[:2]
    try: return urllib.request.urlopen(f"http://{host}:{port}/{path}", timeout=t).status == 200
    except Exception: return False


def wait_ready(ip, timeout=240):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if http_ok(ip): return time.time() - t0
        time.sleep(1)
    raise TimeoutError(f"desktop {ip} not ready in {timeout}s")


EVAL_TIMEOUT = 600


def evaluate_with_timeout(env):
    """OSWorld scoring with a time limit. Some evaluator postconfigs never return (e.g. Calc tasks press Ctrl+S, LibreOffice shows
    the "Keep current format?" dialog, then `open` of the gold file waits forever for its window), which would hold the whole run
    open. On timeout the rollout scores 0 and is marked; the stuck request is abandoned in a daemon thread."""
    box = {}
    def run():
        try: box["r"] = float(env.evaluate())
        except Exception as e: box["e"] = e
    th = threading.Thread(target=run, daemon=True); th.start(); th.join(EVAL_TIMEOUT)
    if th.is_alive(): raise TimeoutError(f"scoring timed out after {EVAL_TIMEOUT}s")
    if "e" in box: raise box["e"]
    return box["r"]


# ---------------------------------------------------------------- one rollout

class ReplayAgent:
    """A11yAgent stand-in that replays a recorded rollout's chat.jsonl. Each recorded element (role, name) is looked up in the current
    rows (nearest box if several match); no match -> the recorded coordinates. Writes chat.jsonl in A11yAgent's format."""
    def __init__(self, src):
        self.steps = [json.loads(l) for l in open(src / "chat.jsonl")]; self.n, self.log = 0, None
        self.stats = {"match": 0, "coords": 0, "no_target": 0}

    def reset(self, *_a, **_k): pass

    def _find(self, rec_rows, i, rows):
        role, name, (x, y, w, h) = rec_rows[i]
        c = [j for j, r in enumerate(rows) if r[0] == role and r[1] == name]
        if not c: return None
        return min(c, key=lambda j: abs(rows[j][2][0] + rows[j][2][2] / 2 - x - w / 2) + abs(rows[j][2][1] + rows[j][2][3] / 2 - y - h / 2))

    def predict(self, instruction, obs):
        if self.n >= len(self.steps):   # recording ended early (its rollout errored): stop here
            st = {"action": {"action": "done"}, "rows": [], "code": "DONE"}
        else: st = self.steps[self.n]
        self.n += 1; act = dict(st["action"]); rec_rows = st["rows"]
        if a.replay_latency and st.get("t"): time.sleep(a.replay_latency * max(0.0, st["t"]["llm_end"] - st["t"]["llm_start"]))
        _, rows = linearize(obs["accessibility_tree"]); how = "no_target"
        keys = [k for k in ("id", "from", "to") if isinstance(act.get(k), int) and 0 <= act[k] < len(rec_rows)]
        if keys:
            new = {k: self._find(rec_rows, act[k], rows) for k in keys}
            if all(v is not None for v in new.values()): act.update(new); how = "match"
            else: how = "coords"
        try: code = to_code(act, rows) if how != "coords" else st["code"]
        except Exception: code = st["code"]
        self.stats[how] += 1
        if self.log:
            with open(self.log, "a") as f:
                f.write(json.dumps({"response": st.get("response", ""), "action": act, "code": code, "replay": how,
                                    "rows": [[r, n, list(b)] for r, n, b in rows]}) + "\n")
        return st.get("response", ""), [code]


def rollout(task, domain, k, name, ip, d):
    d.mkdir(parents=True, exist_ok=True); tm = {"copy": name, "t_start": time.time()}
    env = make_env(ip); env._set_task_info(task); env.setup_controller.reset_cache_dir(env.cache_dir)
    agent = (ReplayAgent(REPLAY / domain / f"{task['id']}__g{k}") if REPLAY else A11yAgent(a.model, temperature=a.temperature))
    agent.reset(); agent.log = str(d / "chat.jsonl")
    rid = str(d); reward, steps, err = 0.0, 0, None
    try:
        obs = env._get_obs()
        for n in range(1, a.max_steps + 1):
            if SPEC:
                with SPEC_LOCK: SPEC.decide(task["id"], rid)
            resp, codes = agent.predict(task["instruction"], obs)
            last = json.loads(open(d / "chat.jsonl").read().splitlines()[-1])
            act, rows = last["action"], last["rows"]
            i = act.get("id", act.get("from"))
            hit = {"role": rows[i][0], "name": rows[i][1], "key": f"{rows[i][0]}|{rows[i][1][:60]}"} if isinstance(i, int) and 0 <= i < len(rows) else None
            rec = {"step_num": n, "action_timestamp": time.strftime("%Y%m%d@%H%M%S") + f"{time.time() % 1:.6f}"[2:], "action": json.dumps(act),
                   "a11y_hit": hit, "code": codes[0]}
            if SPEC:
                with SPEC_LOCK: sp = SPEC.reveal(task["id"], rid, act, hit)
                if sp: rec["spec"] = sp
            t_exec = time.time(); obs, _, done, _ = env.step(codes[0]); rec["exec_s"] = round(time.time() - t_exec, 3)
            if obs.get("screenshot"): (d / f"step_{n}.png").write_bytes(obs["screenshot"])
            with open(d / "traj.jsonl", "a") as f: f.write(json.dumps(rec) + "\n")
            steps = n
            if done: break
        tm["t_eval"] = time.time()
        try: reward = evaluate_with_timeout(env)
        except TimeoutError:   # keep evidence of what blocked the scorer, then re-raise
            try:
                (d / "eval_timeout.png").write_bytes(env.controller.get_screenshot() or b"")
                (d / "eval_timeout_windows.txt").write_text(str(env.controller.execute_python_command(
                    "import subprocess; print(subprocess.run(['wmctrl', '-l'], capture_output=True, text=True).stdout)").get("output")))
            except Exception: pass
            raise
    except Exception as e:
        err = repr(e); traceback.print_exc()
    tm.update(t_end=time.time(), steps=steps, error=err, **({"replay": agent.stats} if a.replay else {}))
    (d / "result.txt").write_text(f"{reward}\n"); (d / "timing.json").write_text(json.dumps(tm, indent=1))
    log("rollout_done", task=task["id"], k=k, reward=reward, steps=steps, error=err, secs=round(tm["t_end"] - tm["t_start"], 1))
    return reward


# ---------------------------------------------------------------- one group

# Chrome task setups launch `socat tcp-listen:9222,fork tcp:localhost:1337` to expose Chrome's DevTools port. In forked copies that relay
# is dead (tcp-close drops its open CDP connection from setup; it exits and lingers as a zombie), so OSWorld's CDP getters time out.
# After the fork every copy re-launches the task's own relay command. Pure plumbing, same on every system; Chrome is untouched.
# `podman container clone --live` copies (tfork and CKPT) don't get podman's generated /etc/hosts bind mount: they see the image's empty
# /etc/hosts, so resolving `localhost` falls through to DNS and hangs ~20 s (06's podman network has no working DNS). Restore the
# standard loopback entries in every copy.
HOSTS_FIX = ("[ -s /etc/hosts ] || printf '127.0.0.1\\tlocalhost\\n::1\\tlocalhost ip6-localhost ip6-loopback\\n"
             "ff02::1\\tip6-allnodes\\nff02::2\\tip6-allrouters\\n' > /etc/hosts")


def relay_restart(task):
    for c in task.get("config", []):
        cmd = (c.get("parameters") or {}).get("command")
        cmd = " ".join(cmd) if isinstance(cmd, list) else str(cmd or "")
        if c.get("type") in ("launch", "command", "execute") and cmd.startswith("socat") and "tcp-listen:9222" in cmd:
            # -x: exact full command line, so pkill can't match this shell (whose command line also contains the relay command)
            return f"pkill -xf {shlex.quote(cmd)}; setsid nohup {cmd} >/dev/null 2>&1 < /dev/null &"
    return None


def group(sysm, ti, domain, tid):
    task = json.load(open(OSW / f"evaluation_examples/examples/{domain}/{tid}.json"))
    src = f"osw-{RUN}-t{ti}"; kids = []   # src: container name (podman) or sandbox id (aenv, known after start)
    try:
        MEM.phase[ti] = "boot"; t0 = time.time()
        if BASES: src, ip, pid = BASES[ti]; MEM.add(src, pid, ti)   # --base-fork: a copy of the shared base desktop
        else:
            src, ip, pid = sysm.start_source(src); MEM.add(src, pid, ti)
            boot = wait_ready(ip); time.sleep(20)   # let the session settle (autostarts, a11y bus)
            log("boot", task=tid, secs=round(time.time() - t0, 1), ready_s=round(boot, 1))
        MEM.phase[ti] = "setup"; t1 = time.time()
        make_env(ip).reset(task_config=task); time.sleep(5)
        log("setup", task=tid, secs=round(time.time() - t1, 1))
        log("mem_before_fork", task=tid, **MEM.snapshot(ti))
        MEM.phase[ti] = "fork"; t2 = time.time()
        with FORK_SEM:   # bounded parallel forks; everything forked keeps running concurrently
            t2 = time.time()
            kids = sysm.fork(src, a.rollouts, tid, on_copy=lambda nm, _ad, kp: MEM.add(nm, kp, ti))
        for nm, _, kp in kids: MEM.add(nm, kp, ti)
        fork_s = round(time.time() - t2, 2)
        rr = relay_restart(task)
        for nm, *_ in kids: sysm.run_in(nm, HOSTS_FIX + (f"; {rr}" if rr else ""))
        if a.save_ckpt and a.system == "criu": sysm.save_checkpoint(kids[0][0], Path(a.save_ckpt) / OUT.name / domain / tid, tid)
        time.sleep(5)
        log("fork", task=tid, system=a.system, copies=len(kids), secs=fork_s, **MEM.snapshot(ti))
        MEM.phase[ti] = "rollouts"
        with ThreadPoolExecutor(len(kids)) as ex:
            rs = list(ex.map(lambda x: rollout(task, domain, x[0], x[1][0], x[1][1], OUT / domain / f"{tid}__g{x[0]}"), enumerate(kids)))
        log("group_done", task=tid, rewards=rs, mean=sum(rs) / len(rs), **MEM.snapshot(ti))
    except Exception as e:
        log("group_error", task=tid, error=repr(e)[-1500:]); traceback.print_exc()
    finally:
        MEM.phase[ti] = "teardown"
        names = [src] + [n for n, *_ in kids]; sysm.rm(names)
        for n in names: MEM.drop(n)
        MEM.phase.pop(ti, None)


BASES = []   # --base-fork: per task index (name, addr, pid) forked from the one base desktop


def base_fork(sysm, n):
    """boot one desktop and fork it n times; the base stays up (tfork/AENV copies share its pages) and is torn down at the end."""
    t0 = time.time(); base, ip, pid = sysm.start_source(f"osw-{RUN}-base"); MEM.add(base, pid, "base")
    boot = wait_ready(ip); time.sleep(20)
    log("boot", task="base", secs=round(time.time() - t0, 1), ready_s=round(boot, 1))
    t1 = time.time(); kids = sysm.fork(base, n, "base")
    for nm, ip, kp in kids:
        MEM.add(nm, kp, "base")   # re-owned by its task group once that group starts
        sysm.run_in(nm, HOSTS_FIX); wait_ready(ip, 120)
    log("base_fork", copies=len(kids), secs=round(time.time() - t1, 2), **MEM.snapshot("base"))
    BASES.extend(kids); return base


def main():
    global MEM
    tasks = a.tasks if os.path.isabs(a.tasks) else os.path.join(os.environ.get("PWD", str(HERE)), a.tasks)   # cwd is OSWorld/ by now
    batch = json.load(open(tasks)); todo = [(dom, t) for dom, ids in batch.items() for t in ids]
    if a.limit: todo = todo[:a.limit]
    (OUT / "config.json").write_text(json.dumps(vars(a), indent=1))
    prepare_host(a.system)
    MEM = Mem(); sysm = Aenv() if a.system == "aenv" else Podman(a.system)
    log("run_start", system=a.system, spec=a.spec, tasks=len(todo), rollouts=a.rollouts, host_baseline=MEM.snapshot()["host"])
    base = base_fork(sysm, len(todo)) if a.base_fork else None
    try:
        with ThreadPoolExecutor(a.parallel or len(todo)) as ex:
            list(ex.map(lambda x: group(sysm, x[0], *x[1]), enumerate(todo)))
    finally:
        if base: sysm.rm([base]); MEM.drop(base)
    if SPEC: (OUT / "spec_summary.json").write_text(json.dumps(SPEC.summary(), indent=1))
    log("run_done")


if __name__ == "__main__":
    main()
