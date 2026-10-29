# Restoring a live clone from disk — `podman container tfork-restore`

`podman container clone --live --persistent` gives every clone a
durable checkpoint: while the clone runs on CoW-shared memory, CRIU writes
the source's memory to the clone's image dir (`pages-*.img`).
`podman container tfork-restore` turns such an image back into a running
container.

```bash
PODMAN=./podman-tfork.sh   # with CONTAINERS_STORAGE_CONF pointing at the btrfs store

sudo $PODMAN container clone --live --persistent=async --name c1 src
sudo $PODMAN container tfork-restore --name c1-restored c1
```

The restored container is a new, ordinary libpod container: its own
name, ID, network address, published ports, cgroup and rootfs.  The
clone it came from is left untouched and may be running or stopped.

## Usage

```
podman container tfork-restore [--name NAME] CLONE
```

| Argument | Meaning |
|---|---|
| `CLONE` | name or ID of a clone made with `--live --persistent[=async\|sync]` |
| `--name` | name of the new container (default `CLONE-restored`) |

Prints the new container's ID.  Local podman only (not the remote
client).

The image is restored as it was **when the clone was made** — the
source's memory and the source's rootfs at that instant — not the clone's
state after it started running.  For `--copies=N` all copies share one
image, so restoring any of them gives the same result.

## Requirements

- The clone was created with `--persistent`; plain `--live` clones have
  no image on disk.
- Its dump is finished: `podman inspect CLONE --format '{{.Tfork.DumpStatus}}'`
  is `done`.  For an incremental clone (`--with-previous`) every ancestor
  in the chain must be `done` and still present.
- The image was written by a crun that records `descriptors.json`
  (the stdio targets of the source).  Images from older builds are
  rejected with a message saying so; re-create the clone.
- The clone's bundle still holds `snap-ro` (the dump-time rootfs).  True
  for the default mode and for non-recursive `--tfork-overlay-btrfs`.
  Recursive overlay clones (overlay clone of an overlay clone) don't keep
  their dump-time rootfs and are refused.

## What it does

1. Checks the dump state of the clone and of every chain ancestor.
2. Creates a bundle `<graphroot>/tfork-bundles/<new-id>/`:
   - `rootfs` — writable btrfs snapshot of the clone's `snap-ro`, with
     stale unix-socket files removed;
   - `img` — reflink copy of the clone's image dir (restore never writes
     into the original); an incremental image's `parent` link is
     re-pointed, relative, at the parent clone's image dir;
   - `config.json` — the clone's OCI spec with a new hostname, the
     network namespace path dropped and
     `cgroupsPath = <CgroupParent>/libpod-<new-id>`.
3. Runs `crun restore --detach --tcp-close --file-locks` on that bundle.
   crun reads `img/descriptors.json` and reconnects the container's
   stdout/stderr to a pipe served by the per-container stdio helper,
   which writes the log for `podman logs` and serves an attach socket.
   CRIU creates fresh pid, mount, net,
   uts, ipc and time namespaces; established TCP connections come back
   closed.
4. Registers the container in libpod, attaches it to the networks of the
   nearest container in the clone's lineage that has any (netavark; new
   IP), re-publishes the source's port mappings on new host ports, and
   starts an exit watcher.

`podman inspect NEW --format '{{.Tfork.SourceID}}'` names the clone the
container was restored from.

## Lifecycle

| Operation | Effect |
|---|---|
| `podman ps / inspect / exec / logs / port` | as for any container |
| `podman stop NEW` | stops it |
| `podman rm NEW` | removes it and reaps its bundle |
| `podman stop CLONE` | **keeps** a persistent clone's bundle and image, so it can still be restored |
| `podman rm CLONE` | reaps the clone's bundle **including its image**; restoring from it is no longer possible |

Restore the same clone as many times as you like; each restore is an
independent container.

## Incremental chains (`--with-previous`)

```bash
sudo $PODMAN container clone --live --persistent --name c1 src                  # full
sudo $PODMAN container clone --live --persistent --with-previous --name c2 src  # delta onto c1
sudo $PODMAN container tfork-restore --name c2-restored c2                      # reads c2 + c1
```

An incremental image stores only pages that changed since its parent; the
rest are read through the parent's image at restore time.  Rules:

- Every persistent dump resets the source's soft-dirty tracking, so
  `--with-previous` chains onto the source's **most recent persistent
  dump** — recorded in the source's state before the dump runs — and on
  nothing else.
- If that dump is no longer held by a clone (the clone failed and was
  rolled back, or was removed), `--with-previous` takes a full dump and
  warns: `the last tracked dump of SRC (...) is no longer held by a clone;
  taking a full dump`.
- A source that was never dumped with `--persistent` is rejected.
- Removing a chain parent (`podman rm`) deletes images its children still
  need; their restore then fails with `walk tfork chain of X: lookup
  parent …`.  Keep parents until their children are gone.

Chains work across clone-of-clone too (`src → g1 → g2 …`, any
`--copies`).

## Timeouts

| Knob | Default | Applies to |
|---|---|---|
| `CRIU_TFORK_RESTORE_WAIT_MS` | 60000 | CRIU's budget for a **live clone's** restore to bring all tasks up |
| `PODMAN_TFORK_CLONE_READY_TIMEOUT_SECS` | 120 | podman's wait for a live clone (dump + restore) |
| — | 10 min | podman's wait for `crun restore` in `tfork-restore` |

A clone's tasks fault in their files from a cold rootfs snapshot.  On
rotational storage — especially right after a `--persistent=sync` dump
has written GBs that are still being flushed — a desktop workload needs
20–40 s.

## Logs

| Where | What |
|---|---|
| `<new bundle>/crun-restore.log` | crun's own messages |
| `<new bundle>/restore.log` | CRIU restore log (`-v4`) |
| `/run/libpod/tfork/<id[:12]>/0/clone.log` | the container's stdout/stderr (`podman logs`) |
| `<clone bundle>/img/tfork.log` | the original dump (`CRIU_TFORK_LOG_LEVEL=3` or `4` for detail) |

On failure the new bundle is removed; set `PODMAN_TFORK_NO_REAP=1` to
keep it for inspection.

## Limits and untested areas

Verified on `ghcr.io/wuklab/webtop:ubuntu-kde-fb313e8` with chromium,
LibreOffice and GIMP running: async and sync images, incremental chains
four deep, clone-of-clone three levels deep with `--copies=2..4`, and
restores from running and stopped clones.

Not supported or not yet tested:

- restore after a host reboot (`/run` state and `clone.log` are lost;
  bundles on btrfs survive) — untested;
- sources started with `-t` (TTY) — untested;
- named volumes and extra bind mounts — untested;
- `--tfork-overlay-btrfs` clones — untested (recursive ones are refused);
- live-cloning a restored container — untested;
- `podman attach` to a restored container — untested;
- the remote client — not supported.

## Troubleshooting

- **`a complete checkpoint for this container cannot be found`** — that
  is `podman container restore`, the regular checkpoint path, which does
  not handle clone images.  Use `tfork-restore`.
- **`tfork image of X is inflight, not done`** — an async dump is still
  writing; wait for `.Tfork.DumpStatus` to become `done`.
- **Clones or restores time out and `img/tfork.log` is huge with
  `cg: adding cgroup` lines** — leftover cgroups, often cgroup-v1 named
  hierarchies (`name=zdtmtst`) created by CRIU's zdtm test suite.  Every
  dump walks them.  `sudo ./tfork-cgroup-cleanup.sh` reaps them; don't run
  zdtm on a host used for podman tfork.  Draining a named hierarchy
  completely can leave its processes pointing at a hierarchy that can no
  longer be mounted, and CRIU then fails with `Unable to create the cgroup
  (name=…) file system` until those processes are gone (or a reboot).
- **A restored chromium looks frozen** — Chromium throttles timers of
  hidden tabs to about one wake-up a minute after five minutes in the
  background.  Bring its window to the front before judging.

## Related changes

The feature depends on these changes elsewhere in the tree:

| Component | Change |
|---|---|
| crun | `crun tfork` writes `descriptors.json` into the image dir; a source that is itself a clone is frozen via its real cgroup (its crun state has no `cgroup-path`) |
| CRIU | incremental dumps keep each task's image uid from the parent image (keyed by pid in the dump root's pid namespace); pre-dumps write `pstree.img`; the async memdump never writes a `PE_PARENT` range the parent image cannot serve; live-clone restore budget 60 s |
| podman | relative `--parent-path`; `--with-previous` chains onto the last tracked dump; a persistent clone's bundle survives `stop`; failed clones no longer leak their dumpd holder |

Regression tests (in the full `os4agent` tree): `criu/test/zdtm/static/incr_uid_shift`,
`test/clone_live_with_previous_intervening_dump_test.sh`,
`test/clone_live_dumpd_holder_failed_clone_test.sh`.
