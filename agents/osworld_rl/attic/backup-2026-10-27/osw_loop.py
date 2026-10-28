"""OSWorld GRPO + LoRA loop driven from the env host (06); the GPU pod only serves vLLM and trains (counterpart of webarena_rl/wa_loop.py).
  nohup venv/bin/python osw_loop.py --exp osw_criu --system criu --epochs 4 --pod root@IP --pod-port PORT > traces/osw_criu_loop.log 2>&1 &
Per epoch: forked rollouts here (osw_run.py: one desktop per task -> setup -> fork G copies -> G rollouts; memory profiled) -> rsync
chat.jsonl/result.txt to the pod -> train_grpo.py on the pod (LoRA GRPO update) -> hot-load the adapter into vLLM as pol<e+1> -> copy the
adapter + its training log + the training data into <root>/pod_backup/<exp>/ here. Writes <exp>_loop.jsonl (one line per epoch).
Needs: vLLM on the pod with --enable-lora (VLLM_ALLOW_RUNTIME_LORA_UPDATING=True), train_grpo.py at /root/osworld_rl, the model in
HF_HOME=/root/hf on the pod, ssh key --pod-key. Opens the forward tunnel <llm-port> -> pod:8000 itself."""
import argparse, glob, json, os, statistics as st, subprocess, time, urllib.request
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--exp", required=True); ap.add_argument("--epochs", type=int, default=4); ap.add_argument("--start-epoch", type=int, default=0)
ap.add_argument("--system", default="criu"); ap.add_argument("--spec", default="off")
ap.add_argument("--run-args", default="--parallel 0 --full-memcopy 1 --save-ckpt /mnt/btrfs/osw_ckpts",
                help="extra osw_run.py arguments (default: all task groups at once, CKPT without CoW, keep CRIU images)")
ap.add_argument("--pod", required=True, help="user@host of the GPU pod"); ap.add_argument("--pod-port", default="22")
ap.add_argument("--pod-key", default=os.path.expanduser("~/.ssh/runpod_wa"))
ap.add_argument("--base", default="Qwen/Qwen3-VL-8B-Instruct"); ap.add_argument("--base-served", default="qwen3vl8b")
ap.add_argument("--tasks", default=str(Path(__file__).resolve().parent / "grpo_batch.json")); ap.add_argument("--rollouts", type=int, default=8); ap.add_argument("--max-steps", type=int, default=15)
ap.add_argument("--lr", type=float, default=5e-5); ap.add_argument("--minibatches", type=int, default=4); ap.add_argument("--init-adapter")
ap.add_argument("--llm-port", default="8100", help="local end of the tunnel to the pod's vLLM (8000 is AENV's)")
a = ap.parse_args()

HERE = Path(__file__).resolve().parent
SSHO = ["-i", a.pod_key, "-o", "ServerAliveInterval=30", "-o", "StrictHostKeyChecking=accept-new"]
POD = ["ssh", *SSHO, "-p", a.pod_port, a.pod]; RSH = f"ssh {' '.join(SSHO)} -p {a.pod_port}"
BK = HERE / "pod_backup" / a.exp; BK.mkdir(parents=True, exist_ok=True)
LOG = open(BK / f"{a.exp}_loop.jsonl", "a")


def sh(cmd, **k):
    print("+", " ".join(cmd) if isinstance(cmd, list) else cmd, flush=True); return subprocess.run(cmd, check=True, **k)


def llm_up():
    try: return urllib.request.urlopen(f"http://127.0.0.1:{a.llm_port}/v1/models", timeout=5).status == 200
    except Exception: return False


def ensure_tunnel():
    if llm_up(): return
    sh(["ssh", "-f", "-N", *SSHO, "-o", "ExitOnForwardFailure=yes", "-p", a.pod_port, "-L", f"{a.llm_port}:localhost:8000", a.pod])
    for _ in range(30):
        if llm_up(): return
        time.sleep(2)
    raise SystemExit("tunnel up but vLLM not answering on the pod")


def summary(run):
    rs = [float(open(f).read()) for f in glob.glob(f"{HERE}/traces/{run}/*/*__g*/result.txt")]
    return dict(rollouts=len(rs), mean_reward=st.mean(rs) if rs else None, successes=sum(r > 0 for r in rs))


adapter = a.init_adapter
for e in range(a.start_epoch, a.epochs):
    run, served = f"{a.exp}_e{e}", (a.base_served if e == 0 else f"{a.exp}-pol{e}")   # per-experiment adapter names: vLLM keeps old ones loaded
    ensure_tunnel(); t0 = time.time(); R = HERE / "traces" / run
    if not (e == a.start_epoch and os.environ.get("SKIP_ROLLOUT")):
        sh(["sudo", "rm", "-rf", str(R)])
        subprocess.run(["sudo", "env", f"DOUBAO_API_URL=http://127.0.0.1:{a.llm_port}/v1", "DOUBAO_API_KEY=x", str(HERE / "venv/bin/python"),
                        str(HERE / "osw_run.py"), "--system", a.system, "--spec", a.spec, "--model", served, "--tasks", a.tasks,
                        "--rollouts", str(a.rollouts), "--max-steps", str(a.max_steps), "--result-dir", str(R), *a.run_args.split()],
                       stdout=open(f"{R}.log", "w"), stderr=subprocess.STDOUT, check=False)
        sh(["sudo", "chown", "-R", f"{os.getuid()}:{os.getgid()}", str(R), f"{R}.log"])
    rollout_secs = time.time() - t0
    s = summary(run); print(f"epoch {e} {run}: {s}", flush=True)
    # training input = chat.jsonl + result.txt per rollout (what train_grpo.py globs: **/<task>__g<k>/)
    (BK / "data" / run).mkdir(parents=True, exist_ok=True); (BK / "adapters").mkdir(exist_ok=True)
    sh(["rsync", "-a", "--include=*/", "--include=chat.jsonl", "--include=result.txt", "--exclude=*", f"{R}/", str(BK / "data" / run) + "/"])
    sh(POD + [f"mkdir -p /root/data/{run} /root/adapters/{a.exp}"])
    sh(["rsync", "-a", "-e", RSH, str(BK / "data" / run) + "/", f"{a.pod}:/root/data/{run}/"])
    out = f"/root/adapters/{a.exp}/e{e + 1}"
    cmd = (f"cd /root/osworld_rl && HF_HOME=/root/hf /root/venv/bin/python train_grpo.py --base {a.base} --data /root/data/{run} --out {out} "
           f"--lr {a.lr} --minibatches {a.minibatches}" + (f" --init-adapter {adapter}" if adapter else ""))
    t1 = time.time(); sh(POD + [cmd + f" 2>&1 | tee /root/train_e{e + 1}.log"])
    if subprocess.run(POD + [f"test -f {out}/adapter_model.safetensors"]).returncode:
        LOG.write(json.dumps(dict(epoch=e, run=run, served=served, **s, rollout_secs=rollout_secs, stopped="no GRPO signal (every group has identical rewards)")) + "\n"); LOG.flush()
        print(f"STOP: epoch {e} has no reward variance, nothing to train on"); break
    adapter = out
    sh(POD + [f"curl -sf -X POST localhost:8000/v1/load_lora_adapter -H 'Content-Type: application/json' "
              f"-d '{json.dumps({'lora_name': f'{a.exp}-pol{e + 1}', 'lora_path': out})}'"])
    sh(["rsync", "-a", "-e", RSH, f"{a.pod}:{out}/", str(BK / "adapters" / f"e{e + 1}") + "/"])
    sh(["rsync", "-a", "-e", RSH, f"{a.pod}:/root/train_e{e + 1}.log", str(BK / "adapters" / f"e{e + 1}") + "/"])
    stats = json.load(open(BK / "adapters" / f"e{e + 1}" / "train_stats.json"))
    LOG.write(json.dumps(dict(epoch=e, run=run, served=served, **s, rollout_secs=rollout_secs, train_secs=time.time() - t1,
                              adapter=str(BK / "adapters" / f"e{e + 1}"), trained=stats.get("samples"))) + "\n"); LOG.flush()
print("loop done")
