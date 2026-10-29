"""Does a desktop come back from disk the way the prefix cache needs? docs/TFORK_RESTORE.md's path, on a rollout copy:

  sudo venv/bin/python -I test_tfork_restore.py [--overlay 1|0] [--keep]

source desktop + OSWorld task setup (calc 42e0a640) -> rollout copy (as osw_run.py forks: --persistent=async, with
--tfork-overlay-btrfs when --overlay 1) -> action A in the copy -> save: `clone --live --persistent=async --copies=1`
of the copy, wait for its dump, stop it -> action B in the copy (so the copy has moved on) -> restore:
`tfork-restore` of the stopped clone -> the restored desktop's observation must equal the copy's after A (not after
B), and it must keep working (action C). Observations are the accessibility rows the policy is prompted with.
Writes traces/restore_test_o<overlay>/result.json.
"""
import json, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I leaves the script dir off sys.path

OVERLAY = int(sys.argv[sys.argv.index("--overlay") + 1]) if "--overlay" in sys.argv else 1
KEEP = "--keep" in sys.argv
REPO = "/home/yutong/Repos/mlsys-resubmission/os4agent-wuklab-mlsys"
sys.argv = ["osw_run.py", "--system", "tfork", "--result-dir", f"traces/restore_test_o{OVERLAY}", "--os4agent", REPO,
            "--storage-conf", "/mnt/data/btrfs/podman/storage.conf", "--overlay-rootfs", str(OVERLAY)]
import osw_run as R  # noqa: E402  (parses the argv above)
from a11y_owl_agent import linearize  # noqa: E402

TASK = json.load(open(R.OSW / "evaluation_examples/examples/libreoffice_calc/42e0a640-4f19-4b28-973d-729602b5a4a7.json"))
sysm, made, res = R.Podman("tfork"), [], {"overlay": OVERLAY}


def rows(env):
    _, rs = linearize(R.observe(env)["accessibility_tree"])
    return [(r[0], r[1]) for r in rs], [tuple(r[2]) for r in rs]


def act(env, text):
    env.step(f"import pyautogui\npyautogui.write('{text}', interval=0.02)\npyautogui.press('enter')")
    time.sleep(2)


def step(name, fn):
    t0 = time.time()
    out = fn()
    res[f"{name}_s"] = round(time.time() - t0, 1)
    print(f"{time.strftime('%T')} {name}: {res[f'{name}_s']} s", flush=True)
    return out


def dump_status(name):
    return sysm.p("inspect", name, "--format", "{{.Tfork.DumpStatus}}").stdout.strip()


try:
    src, addr, _ = step("boot", lambda: sysm.start_source("osw-rt-src"))
    made.append(src)
    R.wait_ready(addr)
    time.sleep(20)
    step("task_setup", lambda: R.make_env(addr).reset(task_config=TASK))
    time.sleep(5)
    copy, caddr, _ = step("fork_copy", lambda: sysm.fork(src, 1, "restore_test"))[0]
    made.append(copy)
    R.fixup_copies(sysm, [(copy,)], TASK)
    env = R.task_env(caddr, TASK)
    act(env, "restoretestA")
    after_a = rows(env)

    def save():
        sysm.p("exec", copy, "true")
        out = sysm._clone(copy, f"{copy[:12]}-pfx", ["--copies=1", "--persistent=async", "--tfork-tcp-close",
                                                     f"--tfork-ghost-limit={64 << 20}"], "pfx_clone")
        c = R.container_ids(out)[0]
        made.append(c)
        while (s := dump_status(c)) != "done":
            if s not in ("inflight", "pending", ""):
                raise RuntimeError(f"dump status {s!r}")
            time.sleep(1)
        sysm.p("stop", "-t", "0", c)
        return c
    clone = step("save", save)
    res["clone_dump_status_after_stop"] = dump_status(clone)
    act(env, "restoretestB")
    after_b = rows(env)

    def restore():
        new = sysm.p("container", "tfork-restore", "--name", f"{clone[:12]}-r", clone).stdout.strip().splitlines()[-1]
        made.append(new)
        raddr, _ = sysm.info(new)
        R.fixup_copies(sysm, [(new,)], TASK)
        R.wait_ready(raddr)
        return new, raddr
    new, raddr = step("restore", restore)
    renv = R.task_env(raddr, TASK)
    restored = rows(renv)
    res.update(rows_after_a=len(after_a[0]), rows_after_b=len(after_b[0]), rows_restored=len(restored[0]),
               a_vs_b_same=after_a[0] == after_b[0],
               restored_equals_after_a=restored[0] == after_a[0], restored_boxes_equal_after_a=restored[1] == after_a[1],
               restored_equals_after_b=restored[0] == after_b[0],
               diff_vs_a=[r for r in restored[0] if r not in after_a[0]][:10] + ["--"] + [r for r in after_a[0] if r not in restored[0]][:10])
    act(renv, "restoretestC")
    res["restored_works"] = rows(renv)[0] != restored[0]
    res["restored_source"] = sysm.p("inspect", new, "--format", "{{.Tfork.SourceID}}", check=False).stdout.strip()[:12]
except Exception as e:
    res["error"] = repr(e)[-1500:]
finally:
    if not KEEP:
        sysm.rm(made[::-1])
    (R.OUT / "result.json").write_text(json.dumps(res, indent=1))
    print(json.dumps({k: v for k, v in res.items() if k != "diff_vs_a"}, indent=1))
    print("diff restored vs after A (only in restored -- only in after A):", res.get("diff_vs_a"))
