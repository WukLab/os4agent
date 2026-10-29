"""Copy a docker image into the btrfs podman store that tfork uses, without `podman pull docker-daemon:` (which spools
a full `docker save` tarball at ~28 MB/s: about an hour for wa-shop-orig-browser). Same content, one layer:
  python3 agents/webarena_rl/setup/import_to_podman.py [image]          (default wa-shop-orig-browser:latest; asks sudo)
Starts the image idle under docker (entrypoint `sleep`, no network, so no service runs or writes), tars its root
filesystem from /proc/<pid>/root (numeric owners, xattrs, ACLs; leaves out /proc, /sys, /dev and the files docker
bind-mounts: /etc/hosts, /etc/hostname, /etc/resolv.conf) into `podman import`, carrying over the image's
entrypoint, cmd, workdir, user, env and exposed ports. Removes the helper container at the end."""
import json, os, subprocess, sys, time

IMAGE = sys.argv[1] if len(sys.argv) > 1 else "wa-shop-orig-browser:latest"
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
PODMAN = ["sudo", "-n", "env", "CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf",
          f"CONTAINERS_CONF={REPO}/agents/webarena_rl/containers-os4agent.conf", "TMPDIR=/mnt/data/btrfs/podman/tmp",
          f"{REPO}/podman-tfork.sh"]
HELPER = "podman-import-helper"


def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip()


cfg = json.loads(sh("docker", "image", "inspect", IMAGE))[0]["Config"]
changes = []
if cfg.get("Entrypoint"):
    changes.append(f"ENTRYPOINT {json.dumps(cfg['Entrypoint'])}")
if cfg.get("Cmd"):
    changes.append(f"CMD {json.dumps(cfg['Cmd'])}")
if cfg.get("WorkingDir"):
    changes.append(f"WORKDIR {cfg['WorkingDir']}")
if cfg.get("User"):
    changes.append(f"USER {cfg['User']}")
for e in cfg.get("Env") or []:
    k, v = e.split("=", 1)
    changes.append(f"ENV {k}={json.dumps(v)}")
for p in cfg.get("ExposedPorts") or {}:
    changes.append(f"EXPOSE {p}")

subprocess.run(["docker", "rm", "-f", HELPER], capture_output=True)
sh("docker", "run", "-d", "--name", HELPER, "--network", "none", "--entrypoint", "sleep", IMAGE, "infinity")
try:
    pid = sh("docker", "inspect", "-f", "{{.State.Pid}}", HELPER)
    t0 = time.time()
    tar = subprocess.Popen(["sudo", "-n", "tar", "-C", f"/proc/{pid}/root", "--one-file-system", "--numeric-owner",
                            "--xattrs", "--xattrs-include=*", "--acls", "-cf", "-",
                            "--exclude=./proc", "--exclude=./sys", "--exclude=./dev", "--exclude=./etc/hosts",
                            "--exclude=./etc/hostname", "--exclude=./etc/resolv.conf", "."], stdout=subprocess.PIPE)
    imp = subprocess.run([*PODMAN, "import", *[x for c in changes for x in ("--change", c)], "-", IMAGE],
                         stdin=tar.stdout, capture_output=True, text=True)
    tar.stdout.close()
    tar_rc = tar.wait()
    print(f"tar rc={tar_rc}, podman import rc={imp.returncode} in {time.time() - t0:.0f} s")
    print(imp.stdout[-300:], imp.stderr[-1500:])
    if imp.returncode or tar_rc not in (0, 1):   # tar exits 1 for "file changed as we read it" warnings
        sys.exit(1)
finally:
    subprocess.run(["docker", "rm", "-f", HELPER], capture_output=True)
print(sh(*PODMAN, "images", "--format", "{{.Repository}}:{{.Tag}} {{.Size}} {{.Created}}"))
