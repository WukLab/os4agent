"""GRPO outer loop, run ON the pod:  rollouts (on 02) -> pull traces -> LoRA update -> hot-load adapter -> next epoch.
  python grpo_loop.py --exp a11yowl --epochs 3 --start-epoch 1 --baseline a11y_owl_e0
Needs: vLLM started with LORA=1 GPU_UTIL=0.4 (runpod_up.sh), the reverse tunnel to 02, ssh key ~/.ssh/wuk, train_grpo.py next to this file.
Epoch 0 is the untouched model (--baseline names an existing traces dir on 02 and skips its rollouts)."""
import argparse, json, os, statistics as st, subprocess, sys, time, urllib.request
ap = argparse.ArgumentParser()
ap.add_argument("--exp", required=True); ap.add_argument("--epochs", type=int, default=3); ap.add_argument("--start-epoch", type=int, default=0)
ap.add_argument("--baseline", help="existing traces dir name on 02 used as epoch-0 data"); ap.add_argument("--base", default="mPLUG/GUI-Owl-7B")
ap.add_argument("--base-served", default="guiowl7b"); ap.add_argument("--tasks", default="grpo_batch.json"); ap.add_argument("--envs", type=int, default=10)
ap.add_argument("--rollout-timeout", type=int, default=4800); ap.add_argument("--lr", type=float, default=5e-5); ap.add_argument("--minibatches", type=int, default=4)
ap.add_argument("--init-adapter"); ap.add_argument("--max-steps", type=int, default=30)
# env selection (defaults = OSWorld). WebArena: --root /mnt/ssd2/vikranth/webarena --runner webarena_rl/run_webarena.sh --pre true --tasks webarena_batch.json
ap.add_argument("--root", help="env root on the env host (default $WUK_ROOT)"); ap.add_argument("--runner", default="./run_02.sh")
ap.add_argument("--pre", default="source docker.env", help="shell run in --root before the rollout"); a = ap.parse_args()
E = os.environ.get  # env host (02 or 06) from .env
H, P, U, ROOT = E("WUK_HOST", "wuklab-01.ucsd.edu"), E("WUK_PORT", "1002"), E("WUK_USER", "vikranth"), a.root or E("WUK_ROOT", "/mnt/btrfs/vikranth/osworld"); SSH = ["ssh", "-i", os.path.expanduser("~/.ssh/wuk"), "-p", P, "-o", "ServerAliveInterval=30", f"{U}@{H}"]
RSH = f"ssh -i {os.path.expanduser('~/.ssh/wuk')} -p {P}"
def backup(*paths):
    """Copy adapters / training data / loop log back to <root>/pod_backup on the env host (the pod's disk is ephemeral)."""
    for src, dst in paths:
        subprocess.run(SSH + [f"mkdir -p {ROOT}/pod_backup/{os.path.dirname(dst.rstrip('/'))}"], check=False)
        subprocess.run(["rsync", "-a", "-e", RSH, src, f"{U}@{H}:{ROOT}/pod_backup/{dst}"], check=False)
LOG = open(f"/root/{a.exp}_loop.jsonl", "a")
def sh(cmd, **k): print("+", " ".join(cmd) if isinstance(cmd, list) else cmd, flush=True); return subprocess.run(cmd, check=True, **k)
def summary(run):
    rs = []
    out = subprocess.run(SSH + [f"cd {ROOT}/traces/{run}/results && cat */*/*/*/*__g*/result.txt 2>/dev/null"], capture_output=True, text=True).stdout.split()
    rs = [float(x) for x in out]; return dict(rollouts=len(rs), mean_reward=st.mean(rs) if rs else None)
adapter = a.init_adapter
for e in range(a.start_epoch, a.epochs):
    run = a.baseline if (e == 0 and a.baseline) else f"{a.exp}_e{e}"; served = a.base_served if e == 0 else f"pol{e}"
    if not (e == 0 and a.baseline) and not (e == a.start_epoch and os.environ.get("SKIP_ROLLOUT")):
        sh(SSH + [f"cd {ROOT} && {a.pre} && mkdir -p traces/{run} && (nohup python3 host_sampler.py traces/{run}/host.jsonl >/dev/null 2>&1 & echo $! > /tmp/hs_{run}.pid) ; "
                  f"AGENT=a11y ROLLOUTS=8 ROLLOUT_TEMP=1.0 MAX_STEPS={a.max_steps} NUM_ENVS={a.envs} TIMEOUT={a.rollout_timeout} SERVED={served} TASKS={a.tasks} {a.runner} {run}; kill $(cat /tmp/hs_{run}.pid) 2>/dev/null; true"])
    data = f"/root/data/{run}"; os.makedirs(data, exist_ok=True)
    sh(["rsync", "-a", "--include=*/", "--include=chat.jsonl", "--include=result.txt", "--exclude=*", "-e", RSH,
        f"{U}@{H}:{ROOT}/traces/{run}/results/", data + "/"])
    s = summary(run); out = f"/root/adapters/e{e + 1}"
    cmd = [sys.executable, os.path.join(os.path.dirname(__file__), "train_grpo.py"), "--base", a.base, "--data", data, "--out", out, "--lr", str(a.lr), "--minibatches", str(a.minibatches)]
    if adapter: cmd += ["--init-adapter", adapter]
    t0 = time.time(); sh(cmd)
    if not os.path.exists(f"{out}/adapter_model.safetensors"):  # train_grpo.py exits early when no group has reward variance
        LOG.write(json.dumps(dict(epoch=e, run=run, **s, stopped="no GRPO signal (every group has identical rewards)")) + "\n"); LOG.flush()
        print(f"STOP: epoch {e} has no reward variance, nothing to train on"); break
    adapter = out
    req = urllib.request.Request("http://localhost:8000/v1/load_lora_adapter", json.dumps({"lora_name": f"pol{e + 1}", "lora_path": out}).encode(), {"Content-Type": "application/json"})
    print("load adapter:", urllib.request.urlopen(req, timeout=300).read().decode()[:200], flush=True)
    LOG.write(json.dumps(dict(epoch=e, run=run, served=served, **s, train_secs=time.time() - t0, adapter=out, trained=json.load(open(f"{out}/train_stats.json")).get("samples"))) + "\n"); LOG.flush()
    backup((out + "/", f"{a.exp}/adapters/e{e + 1}/"), (data + "/", f"{a.exp}/data/{run}/"), (f"/root/{a.exp}_loop.jsonl", f"{a.exp}/{a.exp}_loop.jsonl"))
print("loop done")
