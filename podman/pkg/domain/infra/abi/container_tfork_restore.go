package abi

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io/fs"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/containers/podman/v5/libpod"
	"github.com/containers/podman/v5/libpod/define"
	"github.com/containers/podman/v5/pkg/domain/entities"
	spec "github.com/opencontainers/runtime-spec/specs-go"
	"github.com/sirupsen/logrus"
	"go.podman.io/storage/pkg/stringid"
	"golang.org/x/sys/unix"
)

const tforkRestoreTimeout = 10 * time.Minute

// ContainerTforkRestore creates a new container from a persistent tfork
// clone's on-disk image: the clone's CRIU image dir restored with
// `crun restore` on top of a writable snapshot of the dump-time rootfs (the
// clone bundle's snap-ro anchor).  The clone itself is left untouched and
// may be running or stopped.
func (ic *ContainerEngine) ContainerTforkRestore(ctx context.Context, nameOrID string, opts entities.ContainerTforkRestoreOptions) (rep *entities.ContainerCreateReport, retErr error) {
	clone, err := ic.Libpod.LookupContainer(nameOrID)
	if err != nil {
		return nil, fmt.Errorf("tfork clone %q: %w", nameOrID, err)
	}
	imgDir := clone.TforkImgDir()
	if imgDir == "" || clone.TforkPersistent() == "" {
		return nil, fmt.Errorf("%s has no persistent tfork image (create it with `podman container clone --live --persistent`): %w", clone.Name(), define.ErrInvalidArg)
	}
	if err := tforkRestoreGate(clone); err != nil {
		return nil, err
	}

	snapRO := filepath.Join(filepath.Dir(imgDir), "snap-ro")
	fi, err := os.Lstat(snapRO)
	if err != nil {
		return nil, fmt.Errorf("dump-time rootfs of %s: %w", clone.Name(), err)
	}
	if fi.Mode()&os.ModeSymlink != 0 {
		return nil, fmt.Errorf("%s is a recursive --tfork-overlay-btrfs clone whose dump-time rootfs is not retained: %w", clone.Name(), define.ErrNotImplemented)
	}
	if err := unix.Access(filepath.Join(imgDir, "descriptors.json"), unix.R_OK); err != nil {
		return nil, fmt.Errorf("image of %s has no descriptors.json (written by crun tfork since stdio-restore support); re-create the clone: %w", clone.Name(), err)
	}

	cloneCfg := clone.Config()
	cloneSpec := clone.Spec()
	if cloneCfg == nil || cloneSpec == nil {
		return nil, fmt.Errorf("%s: could not read libpod config or OCI spec", clone.Name())
	}

	newID := stringid.GenerateRandomID()
	name := opts.Name
	if name == "" {
		name = clone.Name() + "-restored"
	}
	bundleDir := filepath.Join(ic.Libpod.StorageConfig().GraphRoot, "tfork-bundles", newID)
	if err := os.MkdirAll(bundleDir, 0o700); err != nil {
		return nil, fmt.Errorf("mkdir bundle: %w", err)
	}
	rootfs := filepath.Join(bundleDir, "rootfs")
	restoredPID := 0
	var registered *libpod.Container
	defer func() {
		if retErr == nil {
			return
		}
		if registered != nil {
			if err := ic.Libpod.RemoveContainer(ctx, registered, true, false, nil); err != nil {
				logrus.Errorf("tfork-restore: remove half-restored container %s: %v", newID, err)
			}
			return
		}
		if restoredPID > 0 {
			_ = unix.Kill(restoredPID, unix.SIGKILL)
		}
		tforkBestEffortBundleReap(bundleDir, 1)
	}()

	if err := tforkSetupSnapSubvolRootfs(snapRO, bundleDir, 0, 1, rootfs); err != nil {
		return nil, fmt.Errorf("restore rootfs: %w", err)
	}
	if err := tforkPurgeSockets(rootfs); err != nil {
		logrus.Warnf("tfork-restore: purge sockets in %s: %v (proceeding)", rootfs, err)
	}
	newImgDir := filepath.Join(bundleDir, "img")
	if err := tforkCopyImageDir(imgDir, newImgDir); err != nil {
		return nil, err
	}

	restoreSpec, err := tforkRestoreSpec(cloneSpec, cloneCfg.CgroupParent, newID, name, clone.ID())
	if err != nil {
		return nil, err
	}
	cb, err := json.MarshalIndent(restoreSpec, "", "  ")
	if err != nil {
		return nil, fmt.Errorf("marshal restore spec: %w", err)
	}
	if err := os.WriteFile(filepath.Join(bundleDir, "config.json"), cb, 0o600); err != nil {
		return nil, fmt.Errorf("write config.json: %w", err)
	}

	runtimeDir := filepath.Join("/run/libpod/tfork", newID[:12], "0")
	if err := os.MkdirAll(runtimeDir, 0o700); err != nil {
		return nil, fmt.Errorf("mkdir %s: %w", runtimeDir, err)
	}
	logPath := filepath.Join(runtimeDir, "clone.log")
	stdioRead, stdioWrite, err := os.Pipe()
	if err != nil {
		return nil, fmt.Errorf("stdio pipe: %w", err)
	}
	defer stdioRead.Close()
	attachSock, err := allocPerCopyAttachSocket(filepath.Join(runtimeDir, "attach"))
	if err != nil {
		logrus.Warnf("tfork-restore: attach socket: %v (attach disabled)", err)
	}

	pidFile := filepath.Join(bundleDir, "pidfile")
	crunLog := filepath.Join(bundleDir, "crun-restore.log")
	// The restored init inherits crun's stdout/stderr via descriptors.json,
	// so crun's own diagnostics go to a file rather than the stdio pipe.
	crunCmd := exec.CommandContext(ctx, defaultCrunPath,
		"--cgroup-manager=cgroupfs", "--log=file:"+crunLog,
		"restore", "--bundle", bundleDir,
		"--image-path", newImgDir, "--work-path", bundleDir,
		"--pid-file", pidFile, "--detach",
		"--tcp-close", "--file-locks",
		newID)
	crunCmd.Stdin = nil
	crunCmd.Stdout = stdioWrite
	crunCmd.Stderr = stdioWrite
	start := time.Now()
	if err := crunCmd.Start(); err != nil {
		stdioWrite.Close()
		return nil, fmt.Errorf("start crun restore: %w", err)
	}
	stdioWrite.Close()

	helperPID, err := spawnTforkStdioHelper(stdioRead, attachSock, logPath, false)
	if attachSock != nil {
		_ = attachSock.Close()
	}
	if err != nil {
		logrus.Warnf("tfork-restore: stdio helper: %v (logs/attach disabled)", err)
	}

	crunDone := make(chan error, 1)
	go func() { crunDone <- crunCmd.Wait() }()
	select {
	case err = <-crunDone:
	case <-time.After(tforkRestoreTimeout):
		_ = crunCmd.Process.Kill()
		err = fmt.Errorf("timed out after %s", tforkRestoreTimeout)
	}
	if err != nil {
		if helperPID > 0 {
			_ = unix.Kill(helperPID, unix.SIGKILL)
		}
		return nil, fmt.Errorf("crun restore of %s failed: %w; see %s and %s", clone.Name(), err,
			crunLog, filepath.Join(bundleDir, "restore.log"))
	}
	data, err := os.ReadFile(pidFile)
	if err != nil {
		return nil, fmt.Errorf("read restored pid: %w", err)
	}
	restoredPID, err = parsePIDBytes(data, pidFile)
	if err != nil {
		return nil, err
	}
	if err := tforkPIDRunning(restoredPID); err != nil {
		return nil, fmt.Errorf("restored init is not running: %w", err)
	}
	logrus.Infof("tfork-restore: %s restored from %s in %s, pid=%d", newID, imgDir, time.Since(start).Round(time.Millisecond), restoredPID)

	cfg, err := buildCloneContainerConfig(cloneCfg, newID, name, rootfs, restoreSpec)
	if err != nil {
		return nil, err
	}
	if cfg.TforkInitPIDStartTime, err = libpod.ReadProcStartTime(restoredPID); err != nil {
		return nil, fmt.Errorf("read restored pid start time: %w", err)
	}
	if len(cloneCfg.PortMappings) > 0 {
		if cfg.PortMappings, err = buildClonePortMappings(cloneCfg.PortMappings); err != nil {
			return nil, err
		}
	}
	cfg.LogPath = logPath
	cfg.LogDriver = define.KubernetesLogging
	cfg.ConmonPidFile = ""
	cfg.ExternalBundlePath = runtimeDir
	cfg.TforkImgDir = ""
	cfg.TforkPersistent = ""
	cfg.TforkParentClone = ""
	cfg.TforkDumpdHolderPid = 0
	cfg.TforkDumpdHolderStartTime = 0
	cfg.TforkSourceID = clone.ID()

	registered, err = ic.Libpod.RegisterExternalContainer(ctx, restoreSpec, cfg, restoredPID)
	if err != nil {
		return nil, fmt.Errorf("register restored container: %w", err)
	}
	if err := ic.Libpod.SetupExternalCloneNetwork(tforkNetworkSource(ic.Libpod, clone), registered, restoredPID); err != nil {
		return nil, fmt.Errorf("network setup: %w", err)
	}
	if out, err := exec.Command("nsenter", "-t", strconv.Itoa(restoredPID), "-n", "--",
		"sh", "-c", "echo '0 0' > /proc/sys/net/ipv4/ping_group_range").CombinedOutput(); err != nil {
		logrus.Warnf("tfork-restore: netns sysctl ping_group_range: %v: %s", err, strings.TrimSpace(string(out)))
	}
	if _, err := spawnTforkExitWatcher(ctx, ic.Libpod, registered, restoredPID); err != nil {
		return nil, fmt.Errorf("exit-watcher spawn: %w", err)
	}
	return &entities.ContainerCreateReport{Id: newID}, nil
}

// tforkRestoreGate refuses images whose async dump, or any incremental-chain
// ancestor's dump, has not finished.
func tforkRestoreGate(c *libpod.Container) error {
	st, err := c.TforkDumpStatus()
	if err != nil {
		return fmt.Errorf("read tfork dump status of %s: %w", c.Name(), err)
	}
	if st != libpod.TforkDumpStateDone {
		return fmt.Errorf("tfork image of %s is %s, not done; wait for the persistent dump to finish", c.Name(), st)
	}
	ancestors, err := c.TforkChainAncestors()
	if err != nil {
		return fmt.Errorf("walk tfork chain of %s: %w", c.Name(), err)
	}
	for _, anc := range ancestors {
		st, err := anc.TforkDumpStatus()
		if err != nil {
			return fmt.Errorf("chain ancestor %s dump status: %w", anc.Name(), err)
		}
		if st != libpod.TforkDumpStateDone {
			return fmt.Errorf("chain ancestor %s of %s is %s; an incremental image needs every ancestor done", anc.Name(), c.Name(), st)
		}
	}
	return nil
}

// tforkCopyImageDir reflink-copies a clone's CRIU image dir so restore-side
// writes (logs, stats) never touch the original, and re-points the
// incremental `parent` link relative to the copy.
func tforkCopyImageDir(src, dst string) error {
	if out, err := exec.Command("cp", "-a", "--reflink=auto", src, dst).CombinedOutput(); err != nil {
		return fmt.Errorf("copy image dir %s -> %s: %s: %w", src, dst, strings.TrimSpace(string(out)), err)
	}
	link := filepath.Join(dst, "parent")
	target, err := os.Readlink(link)
	if errors.Is(err, fs.ErrNotExist) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("read parent link: %w", err)
	}
	if !filepath.IsAbs(target) {
		target = filepath.Join(src, target)
	}
	rel, err := filepath.Rel(dst, target)
	if err != nil {
		return fmt.Errorf("parent image dir %s relative to %s: %w", target, dst, err)
	}
	if err := os.Remove(link); err != nil {
		return fmt.Errorf("replace parent link: %w", err)
	}
	if err := os.Symlink(rel, link); err != nil {
		return fmt.Errorf("replace parent link: %w", err)
	}
	return nil
}

// tforkRestoreSpec derives the restored container's OCI spec from the
// clone's.  The image carries no network namespace (tfork dumps with
// --empty-ns net), so the netns path is dropped and CRIU creates a fresh
// one that SetupExternalCloneNetwork then wires up.
func tforkRestoreSpec(cloneSpec *spec.Spec, cgroupParent, newID, name, cloneID string) (*spec.Spec, error) {
	jb, err := json.Marshal(cloneSpec)
	if err != nil {
		return nil, fmt.Errorf("marshal clone spec: %w", err)
	}
	s := &spec.Spec{}
	if err := json.Unmarshal(jb, s); err != nil {
		return nil, fmt.Errorf("unmarshal clone spec: %w", err)
	}
	if s.Root == nil {
		s.Root = &spec.Root{}
	}
	s.Root.Path = "rootfs"
	s.Hostname = name
	if s.Annotations == nil {
		s.Annotations = map[string]string{}
	}
	s.Annotations["io.podman.tfork.restored-from"] = cloneID
	s.Annotations["io.podman.tfork.clone-id"] = newID
	if s.Linux != nil {
		for i := range s.Linux.Namespaces {
			if s.Linux.Namespaces[i].Type == spec.NetworkNamespace {
				s.Linux.Namespaces[i].Path = ""
			}
		}
		s.Linux.CgroupsPath = filepath.Join(cgroupParent, "libpod-"+newID)
	}
	return s, nil
}

// tforkNetworkSource returns the nearest container in the clone's lineage
// (the clone itself, then its tfork sources) that has networks attached.
func tforkNetworkSource(rt *libpod.Runtime, clone *libpod.Container) *libpod.Container {
	c := clone
	for range 64 {
		if nets, err := c.Networks(); err == nil && len(nets) > 0 {
			return c
		}
		srcID := c.TforkSourceID()
		if srcID == "" {
			break
		}
		src, err := rt.LookupContainer(srcID)
		if err != nil {
			break
		}
		c = src
	}
	return clone
}
