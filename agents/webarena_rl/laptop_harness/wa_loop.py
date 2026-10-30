"""GRPO outer loop driven FROM the env host (06) -- grpo_loop.py with the direction reversed, so the pod never needs access to 06.
  nohup venv/bin/python webarena_rl/wa_loop.py --exp wa_shop --epochs 4 --pod root@IP --pod-port PORT > wa_shop_loop.log 2>&1 &
Per epoch: rollouts here (run_webarena.sh) -> rsync chat.jsonl/result.txt to the pod -> train_grpo.py on the pod (LoRA GRPO update)
-> hot-load the adapter into vLLM as pol<e+1> -> copy adapter + training data + loop log into <root>/pod_backup/<exp>/ here.
Needs: vLLM on the pod started with --enable-lora (VLLM_ALLOW_RUNTIME_LORA_UPDATING=True), train_grpo.py at /root/osworld_rl, ssh key --pod-key.
The forward tunnel 06:8000 -> pod:8000 is (re)opened by this script."""
import argparse, json, os, statistics as st, subprocess, time, glob, urllib.request
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--exp", required=True); ap.add_argument("--epochs", type=int, default=4); ap.add_argument("--start-epoch", type=int, default=0)
ap.add_argument("--pod", required=True, help="user@host of the GPU pod"); ap.add_argument("--pod-port", default="22")
ap.add_argument("--pod-key", default=os.path.expanduser("~/.ssh/runpod_wa"))
ap.add_argument("--base", default="Qwen/Qwen3-VL-8B-Instruct"); ap.add_argument("--base-served", default="qwen3vl8b")
ap.add_argument("--tasks", default="webarena_batch.json"); ap.add_argument("--envs", type=int, default=16); ap.add_argument("--max-steps", type=int, default=30)
ap.add_argument("--rollouts", type=int, default=8); ap.add_argument("--rollout-timeout", type=int, default=4800)
ap.add_argument("--lr", type=float, default=5e-5); ap.add_argument("--minibatches", type=int, default=4); ap.add_argument("--init-adapter")
ap.add_argument("--llm-port", default="8000"); a = ap.parse_args()

HERE = Path(__file__).resolve().parent; ROOT = HERE.parent
SSHO = ["-i", a.pod_key, "-o", "ServerAliveInterval=30", "-o", "StrictHostKeyChecking=accept-new"]
POD = ["ssh", *SSHO, "-p", a.pod_port, a.pod]; RSH = f"ssh {' '.join(SSHO)} -p {a.pod_port}"
BK = ROOT / "pod_backup" / a.exp; BK.mkdir(parents=True, exist_ok=True)
LOG = open(BK / f"{a.exp}_loop.jsonl", "a")


def sh(cmd, **k):
    print("+", " ".join(cmd) if isinstance(cmd, list) else cmd, flush=True); return subprocess.run(cmd, check=True, **k)


def llm_up():
    try: return urllib.request.urlopen(f"http://127.0.0.1:{a.llm_port}/v1/models", timeout=5).status == 200
    except Exception: return False


def ensure_tunnel():
    """06:llm_port -> pod:llm_port. ssh -f backgrounds after the forward is established."""
    if llm_up(): return
    subprocess.run(["pkill", "-f", f"-L {a.llm_port}:localhost:{a.llm_port}"], check=False)
    sh(["ssh", "-f", "-N", *SSHO, "-o", "ExitOnForwardFailure=yes", "-p", a.pod_port, "-L", f"{a.llm_port}:localhost:{a.llm_port}", a.pod])
    for _ in range(30):
        if llm_up(): return
        time.sleep(2)
    raise SystemExit("tunnel up but vLLM not answering on the pod")


def summary(run):
    rs = [float(open(f).read()) for f in glob.glob(f"{ROOT}/traces/{run}/results/*/*/*/*/*__g*/result.txt")]
    return dict(rollouts=len(rs), mean_reward=st.mean(rs) if rs else None, successes=sum(r > 0 for r in rs))


adapter = a.init_adapter
for e in range(a.start_epoch, a.epochs):
    run, served = f"{a.exp}_e{e}", (a.base_served if e == 0 else f"pol{e}")
    ensure_tunnel(); t0 = time.time()
    if not (e == a.start_epoch and os.environ.get("SKIP_ROLLOUT")):
        (ROOT / "traces" / run).mkdir(parents=True, exist_ok=True)
        hs = subprocess.Popen(["python3", str(ROOT / "host_sampler.py"), str(ROOT / "traces" / run / "host.jsonl")])
        env = {**os.environ, "ROLLOUTS": str(a.rollouts), "ROLLOUT_TEMP": "1.0", "MAX_STEPS": str(a.max_steps), "NUM_ENVS": str(a.envs),
               "TIMEOUT": str(a.rollout_timeout), "SERVED": served, "TASKS": a.tasks, "LLM_PORT": a.llm_port,
               "SPEC_WARM": " ".join(str(ROOT / "traces" / f"{a.exp}_e{j}" / "results") for j in range(e) if (ROOT / "traces" / f"{a.exp}_e{j}").exists())}  # TAGE learns earlier epochs first
        subprocess.run(["bash", str(HERE / "run_webarena.sh"), run], env=env, check=False)
        hs.terminate()
    rollout_secs = time.time() - t0
    s = summary(run); print(f"epoch {e} {run}: {s}", flush=True)
    # training input = exactly what grpo_loop.py pulls: chat.jsonl + result.txt per rollout
    (BK / "data" / run).mkdir(parents=True, exist_ok=True); (BK / "adapters").mkdir(exist_ok=True)
    sh(["rsync", "-a", "--include=*/", "--include=chat.jsonl", "--include=result.txt", "--exclude=*", f"{ROOT}/traces/{run}/results/", str(BK / "data" / run) + "/"])
    sh(POD + [f"mkdir -p /root/data/{run} /root/adapters"])
    sh(["rsync", "-a", "-e", RSH, str(BK / "data" / run) + "/", f"{a.pod}:/root/data/{run}/"])
    out = f"/root/adapters/e{e + 1}"
    cmd = f"cd /root/osworld_rl && /root/venv/bin/python train_grpo.py --base {a.base} --data /root/data/{run} --out {out} --lr {a.lr} --minibatches {a.minibatches}"
    if adapter: cmd += f" --init-adapter {adapter}"
    t1 = time.time(); sh(POD + [cmd + f" 2>&1 | tee /root/train_e{e + 1}.log"])
    if subprocess.run(POD + [f"test -f {out}/adapter_model.safetensors"]).returncode:
        LOG.write(json.dumps(dict(epoch=e, run=run, served=served, **s, rollout_secs=rollout_secs, stopped="no GRPO signal (every group has identical rewards)")) + "\n"); LOG.flush()
        print(f"STOP: epoch {e} has no reward variance, nothing to train on"); break
    adapter = out
    sh(POD + [f"curl -sf -X POST localhost:{a.llm_port}/v1/load_lora_adapter -H 'Content-Type: application/json' "
              f"-d '{json.dumps({'lora_name': f'pol{e + 1}', 'lora_path': out})}'"])
    sh(["rsync", "-a", "-e", RSH, f"{a.pod}:{out}/", str(BK / "adapters" / f"e{e + 1}") + "/"])
    sh(["rsync", "-a", "-e", RSH, f"{a.pod}:/root/train_e{e + 1}.log", str(BK / "adapters" / f"e{e + 1}") + "/"])
    stats = json.load(open(BK / "adapters" / f"e{e + 1}" / "train_stats.json"))
    LOG.write(json.dumps(dict(epoch=e, run=run, served=served, **s, rollout_secs=rollout_secs, train_secs=time.time() - t1,
                              adapter=str(BK / "adapters" / f"e{e + 1}"), trained=stats.get("samples"))) + "\n"); LOG.flush()
print("loop done")
