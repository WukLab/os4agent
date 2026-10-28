"""Idempotent: when VM_STORAGE_DIR is set, each OSWorld VM keeps everything it writes in its own dir there instead of under /var/lib/docker
(an HDD root disk on 06 that 16 VMs saturate):  <dir>/boot.qcow2 (the VM's copy-on-write disk, created by the image's install.sh)
and <dir>/storage (firmware/state).   python patch_storage.py <OSWorld dir>
Files under storage/ are written by the container's root, so they are deleted from inside the container before it stops."""
import sys
p = sys.argv[1] + "/desktop_env/providers/docker/provider.py"; s = open(p).read()
if "VM_STORAGE_DIR" in s: sys.exit(print("already patched"))
reps = [
    ("                self.container = self.client.containers.run(",
     "                sd = os.environ.get(\"VM_STORAGE_DIR\")\n"
     "                self.storage_dir = __import__(\"tempfile\").mkdtemp(dir=sd) if sd else None\n"
     "                if self.storage_dir: os.mkdir(f\"{self.storage_dir}/storage\"); open(f\"{self.storage_dir}/boot.qcow2\", \"w\").close()\n"
     "                self.container = self.client.containers.run("),
    ("                    volumes={\n",
     "                    volumes={**({f\"{self.storage_dir}/storage\": {\"bind\": \"/storage\", \"mode\": \"rw\"},\n"
     "                                 f\"{self.storage_dir}/boot.qcow2\": {\"bind\": \"/boot.qcow2\", \"mode\": \"rw\"}} if self.storage_dir else {}),\n"),
    ("\n                self.container.stop()\n",
     "\n                if getattr(self, \"storage_dir\", None): self.container.exec_run(\"sh -c 'rm -rf /storage/*'\")\n"
     "                self.container.stop()\n"),
    ("\n                self.container.remove(v=True)\n",
     "\n                self.container.remove(v=True)\n"
     "                if getattr(self, \"storage_dir\", None): __import__(\"shutil\").rmtree(self.storage_dir, ignore_errors=True)\n"),
]
for old, new in reps:
    assert s.count(old) == 1, old
    s = s.replace(old, new)
open(p, "w").write(s); print("patched")
