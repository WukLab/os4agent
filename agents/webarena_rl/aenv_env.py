"""AgentENV (Firecracker microVM) environments for wa_replay.py --system aenv, after agents/osworld_rl/osw_run.py's Aenv.
A source is `aenv start <template>` (the template wa-shop142: setup/aenv/make_template.sh, the site already running in
its snapshot); copies come from AENV's fork API (POST /sandboxes/<id>/fork). Commands run through `aenv exec`.
The runner reaches a VM's CDP relay (:9222) through a local Forwarder that connects from inside aenv-server's network
namespace (osw_run.py: AENV's HTTP proxy cuts requests at 30 s). Forked sandboxes are matched to their Firecracker
processes by writing each sandbox id into its VM (aenv exec) and reading it back over each new VM's direct address:
osw_run.py reads it from OSWorld's in-guest server on :5000; the WebArena image has none, so each copy serves the tag
with the image's socat on :5000.
Memory: every VM's Firecracker process is in aenv-server's container cgroup (no per-VM cgroup); per VM the runner
reads the VMM's smaps (guest RAM: file-backed snapshot pages + anonymous CoW pages), and for the run the aenv-server
cgroup (server_cgroup())."""
import asyncio, ctypes, json, os, socket, subprocess, threading, time, urllib.request

URL = "http://127.0.0.1:8000"
TAG_PORT = 5000
SOCAT = "/opt/chr/bin/socat"


def setns_net(pid):
    """Move the calling thread into pid's network namespace."""
    with open(f"/proc/{pid}/ns/net") as f:
        if ctypes.CDLL(None, use_errno=True).setns(f.fileno(), 0x40000000):
            raise OSError(ctypes.get_errno(), "setns")


class Forwarder:
    """127.0.0.1:<port> -> TCP relay to a VM port, connecting from inside aenv-server's network namespace
    (osw_run.py's Forwarder)."""

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


def _in_netns(pid, fn):
    """fn() in its own thread inside pid's network namespace."""
    box = {}

    def run():
        try:
            setns_net(pid)
            box["r"] = fn()
        except Exception as e:
            box["e"] = e
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(60)
    if "e" in box:
        raise box["e"]
    return box.get("r")


class Aenv:
    def __init__(self, cli, home, template, key_path):
        self.cli_path, self.template = cli, template
        self.key = open(key_path).read().strip()
        self.env = {**os.environ, "HOME": home}
        self.srv = int(subprocess.run(["docker", "inspect", "aenv-server", "--format", "{{.State.Pid}}"],
                                      capture_output=True, text=True, check=True).stdout)
        self.fw, self.pid, self.ip = {}, {}, {}   # sandbox -> Forwarder / VMM pid / slot address
        self.owned, self.lock = set(), asyncio.Lock()

    def server_cgroup(self):
        return "/sys/fs/cgroup" + open(f"/proc/{self.srv}/cgroup").read().strip().split("::", 1)[1]

    async def cli(self, *args, check=True, timeout=900):
        p = await asyncio.create_subprocess_exec(self.cli_path, *args, env=self.env, stdout=asyncio.subprocess.PIPE,
                                                 stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(p.communicate(), timeout)
        except asyncio.TimeoutError:
            p.kill()
            raise RuntimeError(f"aenv {' '.join(args[:3])} timed out")
        if check and p.returncode:
            raise RuntimeError(f"aenv {' '.join(args[:3])}: rc={p.returncode} {(err or out).decode()[-600:]}")
        return p.returncode, out.decode().strip()

    async def api(self, method, path, body=None, timeout=900):
        def call():
            req = urllib.request.Request(URL + path, method=method,
                                         data=json.dumps(body).encode() if body is not None else None,
                                         headers={"X-API-Key": self.key, "Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=timeout).read() or b"null")
        return await asyncio.to_thread(call)

    async def exec(self, sb, *cmd, check=True, timeout=900):
        """-> (rc, stdout) of cmd in the VM."""
        return await self.cli("exec", sb, "--", *cmd, check=check, timeout=timeout)

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

    async def claim(self, before, n, timeout=120):
        """The n VMMs that became active since `before` (call under self.lock)."""
        t0, new = time.time(), []
        while time.time() - t0 < timeout:
            new = sorted(self.active_vmms() - before - self.owned)
            if len(new) >= n:
                self.owned.update(new[:n])
                return new[:n]
            await asyncio.sleep(0.2)
        raise RuntimeError(f"expected {n} new firecracker VMMs, found {len(new)}")

    def slot_ip(self, vmm):
        """VMM pid -> its slot address: aenv-server routes it via the VMM netns' vpeer address."""
        sh = lambda *c: subprocess.run(c, capture_output=True, text=True, check=True).stdout
        vpeer = sh("nsenter", "-t", str(vmm), "-n", "ip", "-4", "-o", "addr", "show", "dev", "vpeer").split()[3].split("/")[0]
        for line in sh("nsenter", "-t", str(self.srv), "-n", "ip", "-4", "route").splitlines():
            f = line.split()
            if len(f) >= 3 and f[1:3] == ["via", vpeer]:
                return f[0]
        raise RuntimeError(f"no aenv route via {vpeer} (vmm {vmm})")

    def addr(self, sb, port=9222):
        """host:port on this host that reaches the VM's port."""
        if sb not in self.fw:
            self.fw[sb] = Forwarder(self.srv, self.ip[sb], port)
        return f"127.0.0.1:{self.fw[sb].local}"

    async def start(self):
        """A source sandbox from the template -> (sandbox id, VMM pid)."""
        async with self.lock:
            before = self.active_vmms()
            _, out = await self.cli("start", self.template, "--detach", "--timeout", "7200")
            sb = out.split()[-1]
            self.pid[sb] = (await self.claim(before, 1))[0]
        self.ip[sb] = await asyncio.to_thread(self.slot_ip, self.pid[sb])
        return sb, self.pid[sb]

    async def fork(self, src, n):
        """n copies of src -> ([sandbox ids], fork API seconds, pairing seconds)."""
        async with self.lock:
            before, t0 = self.active_vmms(), time.time()
            res = await self.api("POST", f"/sandboxes/{src}/fork", {"count": n, "timeout": 7200})
            if errs := [e.get("error") for e in res if "sandbox" not in e]:
                raise RuntimeError(f"aenv fork errors: {errs}")
            kids = [e["sandbox"]["sandboxID"] for e in res]
            vmms = await self.claim(before, len(kids))
            fork_s = time.time() - t0
        t1 = time.time()
        await self._pair(kids, vmms)
        return kids, fork_s, time.time() - t1

    def _whoami(self, ip):
        def read():
            with socket.create_connection((ip, TAG_PORT), timeout=10) as s:
                return s.recv(256).decode().strip()
        try:
            return _in_netns(self.srv, read)
        except Exception:
            return ""

    async def _pair(self, kids, vmms):
        """Match each forked sandbox to its VMM: tag it via aenv exec (served by socat on :5000), read the tag back over
        each new VM's direct address."""
        for k in kids:
            await self.exec(k, "sh", "-c", f"echo {k} > /tmp/.aenv_sandbox_id; (setsid nohup {SOCAT} "
                            f"tcp-listen:{TAG_PORT},reuseaddr,fork SYSTEM:'cat /tmp/.aenv_sandbox_id' "
                            ">/dev/null 2>&1 < /dev/null &)", timeout=120)
        for vmm in vmms:
            ip = await asyncio.to_thread(self.slot_ip, vmm)
            for _ in range(12):   # a just-resumed VM can be slow to answer
                if (k := await asyncio.to_thread(self._whoami, ip)) in kids:
                    break
                await asyncio.sleep(5)
            else:
                raise RuntimeError(f"aenv fork: VM {ip} answered {k!r}, not one of this fork's copies")
            self.pid[k], self.ip[k] = vmm, ip
        if len({self.ip.get(k) for k in kids}) != len(kids):
            raise RuntimeError("aenv fork: copies and VMs did not pair 1:1")

    async def rm(self, sbs):
        for sb in sbs:
            if f := self.fw.pop(sb, None):
                f.close()
            self.owned.discard(self.pid.pop(sb, None))
            self.ip.pop(sb, None)
            await self.cli("rm", sb, check=False, timeout=120)
