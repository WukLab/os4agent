"""OSWorld GRPO loop, driven from the env host (06). The GPU pod only serves vLLM and trains.

  nohup venv/bin/python osw_loop.py --exp osw_tfork --system tfork --epochs 4 --pod root@IP --pod-port PORT \
      > traces/osw_tfork_loop.log 2>&1 &

Per epoch e:
  1. osw_run.py rollouts on 06 with policy pol<e> (the base model at e=0)  -> traces/<exp>_e<e>/
  2. rsync chat.jsonl + result.txt to the pod, run train_grpo.py there      -> /root/adapters/<exp>/e<e+1>
  3. hot-load the adapter into vLLM as <exp>-pol<e+1>; back it up here     -> pod_backup/<exp>/
One line per epoch goes to pod_backup/<exp>/<exp>_loop.jsonl. Stops early when no group has reward variance.
The pod needs vLLM started with --enable-lora (VLLM_ALLOW_RUNTIME_LORA_UPDATING=True) and train_grpo.py in /root/osworld_rl.
"""
import argparse, glob, json, os, statistics as st, subprocess, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--exp", required=True)
ap.add_argument("--epochs", type=int, default=4)
ap.add_argument("--start-epoch", type=int, default=0)
ap.add_argument("--skip-first-rollout", action="store_true", help="reuse traces/<exp>_e<start-epoch> (resume after a failed train)")
ap.add_argument("--init-adapter", help="adapter to continue from when resuming")
ap.add_argument("--system", required=True, choices=["tfork", "criu", "stock-criu", "aenv"])
ap.add_argument("--spec", default="off")
ap.add_argument("--tasks", default=str(HERE / "grpo_batch32v2.json"))
ap.add_argument("--rollouts", type=int, default=8)
ap.add_argument("--max-steps", type=int, default=15)
ap.add_argument("--run-args", default="--parallel 8", help="extra osw_run.py arguments")
ap.add_argument("--pod", required=True, help="user@host of the GPU pod")
ap.add_argument("--pod-port", default="22")
ap.add_argument("--pod-key", default=os.path.expanduser("~/.ssh/runpod_wa"))
ap.add_argument("--llm-port", default="8100", help="local end of the tunnel to the pod's vLLM (8000 is AENV's)")
ap.add_argument("--base", default="Qwen/Qwen3-VL-8B-Instruct")
ap.add_argument("--base-served", default="qwen3vl8b")
ap.add_argument("--lr", type=float, default=5e-5)
ap.add_argument("--minibatches", type=int, default=4)
ap.add_argument("--longest-first", action="store_true",
                help="start each epoch's task groups longest-first by the previous epoch's slowest rollouts (osw_run.py "
                     "--order-by)")
ap.add_argument("--no-stop", action="store_true",
                help="an epoch with no reward variance trains nothing: keep its policy for the next epoch instead of stopping")
a = ap.parse_args()

SSH_OPTS = ["-i", a.pod_key, "-o", "ServerAliveInterval=30", "-o", "StrictHostKeyChecking=accept-new", "-p", a.pod_port]
POD = ["ssh", *SSH_OPTS, a.pod]
RSYNC = ["rsync", "-a", "-e", "ssh " + " ".join(SSH_OPTS)]
BACKUP = HERE / "pod_backup" / a.exp
BACKUP.mkdir(parents=True, exist_ok=True)


def sh(cmd, **kw):
    print("+", " ".join(cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def llm_up():
    try:
        return urllib.request.urlopen(f"http://127.0.0.1:{a.llm_port}/v1/models", timeout=5).status == 200
    except Exception:
        return False


def ensure_tunnel():
    if llm_up():
        return
    sh(["ssh", "-f", "-N", *SSH_OPTS, "-o", "ExitOnForwardFailure=yes", "-L", f"{a.llm_port}:localhost:8000", a.pod])
    for _ in range(30):
        if llm_up():
            return
        time.sleep(2)
    raise SystemExit("tunnel up but vLLM not answering on the pod")


def summary(run_dir):
    rs = [float(open(f).read()) for f in glob.glob(f"{run_dir}/*/*__g*/result.txt")]
    return dict(rollouts=len(rs), mean_reward=st.mean(rs) if rs else None, successes=sum(r > 0 for r in rs))


def record(**kw):
    with open(BACKUP / f"{a.exp}_loop.jsonl", "a") as f:
        f.write(json.dumps(kw) + "\n")


adapter, keep_policy = a.init_adapter, None
for e in range(a.start_epoch, a.epochs):
    run = f"{a.exp}_e{e}"
    # adapter names are per experiment: vLLM keeps old ones loaded. keep_policy: the last epoch trained nothing (--no-stop)
    served, keep_policy = keep_policy or (a.base_served if e == 0 else f"{a.exp}-pol{e}"), None
    run_dir = HERE / "traces" / run
    ensure_tunnel()

    t0 = time.time()
    if not (e == a.start_epoch and a.skip_first_rollout):
        sh(["sudo", "rm", "-rf", str(run_dir)])
        cmd = ["sudo", "env", f"DOUBAO_API_URL=http://127.0.0.1:{a.llm_port}/v1", "DOUBAO_API_KEY=x",
               str(HERE / "venv/bin/python"), str(HERE / "osw_run.py"), "--system", a.system, "--spec", a.spec,
               "--model", served, "--tasks", a.tasks, "--rollouts", str(a.rollouts), "--max-steps", str(a.max_steps),
               "--result-dir", str(run_dir), *a.run_args.split()]
        cmd += ["--epoch", str(e)]
        warm = [str(HERE / "traces" / f"{a.exp}_e{p}") for p in range(e) if (HERE / "traces" / f"{a.exp}_e{p}").is_dir()]
        if "--spec-exec" in a.run_args.split() and warm:  # the predictor learns the earlier epochs first
            cmd += ["--spec-warm", *warm]
        prev = HERE / "traces" / f"{a.exp}_e{e - 1}" / "events.jsonl"
        if a.longest_first and e > 0 and prev.exists():
            cmd += ["--order-by", str(prev.parent)]
        if "--prefix-cache" in a.run_args.split() and "--prefix-mem" not in a.run_args.split() and e > 0 and prev.exists():
            # disk cache: keep what the previous epoch touched (in memory, --prefix-policy evicts within the budget)
            cmd += ["--prefix-keep-since", str(json.loads(open(prev).readline())["t"])]
        subprocess.run(cmd, stdout=open(f"{run_dir}.log", "w"), stderr=subprocess.STDOUT, check=False)
        sh(["sudo", "chown", "-R", f"{os.getuid()}:{os.getgid()}", str(run_dir), f"{run_dir}.log"])
    rollout_secs = time.time() - t0
    s = summary(run_dir)
    print(f"epoch {e} {run}: {s}", flush=True)

    data = BACKUP / "data" / run
    data.mkdir(parents=True, exist_ok=True)
    sh(["rsync", "-a", "--include=*/", "--include=chat.jsonl", "--include=result.txt", "--exclude=*", f"{run_dir}/", f"{data}/"])
    sh(POD + [f"mkdir -p /root/data/{run} /root/adapters/{a.exp}"])
    sh(RSYNC + [f"{data}/", f"{a.pod}:/root/data/{run}/"])

    out = f"/root/adapters/{a.exp}/e{e + 1}"
    train = (f"cd /root/osworld_rl && HF_HOME=/root/hf /root/venv/bin/python train_grpo.py --base {a.base} "
             f"--data /root/data/{run} --out {out} --lr {a.lr} --minibatches {a.minibatches}"
             + (f" --init-adapter {adapter}" if adapter else ""))
    t1 = time.time()
    sh(POD + [f"{train} 2>&1 | tee /root/train_e{e + 1}.log"])
    if subprocess.run(POD + [f"test -f {out}/adapter_model.safetensors"]).returncode:
        record(epoch=e, run=run, served=served, **s, rollout_secs=rollout_secs, stopped="no group has reward variance")
        if not a.no_stop:
            print(f"STOP: epoch {e} has no reward variance, nothing to train on")
            break
        print(f"epoch {e} has no reward variance; --no-stop: epoch {e + 1} keeps policy {served}")
        keep_policy = served
        continue
    adapter = out

    body = json.dumps({"lora_name": f"{a.exp}-pol{e + 1}", "lora_path": out})
    sh(POD + [f"curl -sf -X POST localhost:8000/v1/load_lora_adapter -H 'Content-Type: application/json' -d '{body}'"])
    keep = BACKUP / "adapters" / f"e{e + 1}"
    keep.mkdir(parents=True, exist_ok=True)
    sh(RSYNC + [f"{a.pod}:{out}/", f"{keep}/"])
    sh(RSYNC + [f"{a.pod}:/root/train_e{e + 1}.log", f"{keep}/"])
    stats = json.load(open(keep / "train_stats.json"))
    record(epoch=e, run=run, served=served, **s, rollout_secs=rollout_secs, train_secs=time.time() - t1,
           adapter=str(keep), trained=stats.get("samples"))
print("loop done")
