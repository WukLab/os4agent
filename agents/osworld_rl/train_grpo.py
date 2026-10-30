"""One LoRA GRPO update from logged OSWorld rollouts. Runs on the GPU pod.

  python train_grpo.py --base Qwen/Qwen3-VL-8B-Instruct --data /root/data/<run> [--init-adapter DIR] --out /root/adapters/e1

Data: <data>/**/<task>__g<k>/{result.txt, chat.jsonl}; each chat.jsonl line is one policy step (messages, response).
Screenshot agent (A11Y_SCREENSHOT=1): chat.jsonl keeps an {"type": "image", "image": "<screenshot>"} placeholder; the image
the model saw at step i (0-based) is the observation after action i, saved as step_<i>.png, preprocessed here exactly as the
agent does (longest side --shot-px, JPEG q85). Step 0's start screenshot is not saved, so those samples are skipped.
Advantage: per task group A = (r - mean) / (std + eps), applied to every step of the rollout; zero-variance groups are skipped.
Loss: PPO-clipped ratio against the pre-update policy on the response tokens, no KL term, token-normalised per minibatch.
"""
import argparse, glob, json, os, random, re, statistics as st, time
import torch

ap = argparse.ArgumentParser()
ap.add_argument("--base", required=True)
ap.add_argument("--data", nargs="*", default=[])
ap.add_argument("--out", required=True)
ap.add_argument("--init-adapter")
ap.add_argument("--lr", type=float, default=5e-5)
ap.add_argument("--minibatches", type=int, default=4)
ap.add_argument("--clip", type=float, default=0.2)
ap.add_argument("--max-len", type=int, default=6144)
ap.add_argument("--lora-r", type=int, default=16)
ap.add_argument("--max-samples", type=int, default=0, help="cap for smoke tests (0 = all)")
ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--dry", action="store_true", help="build the dataset and print stats only")
ap.add_argument("--shot-px", type=int, default=1280, help="the agent's A11Y_SHOT_PX (longest screenshot side)")
a = ap.parse_args()
random.seed(a.seed)
torch.manual_seed(a.seed)

# ---------------------------------------------------------------- data

groups = {}  # task -> {k: (reward, steps)}
for root in a.data:
    for d in glob.glob(f"{root}/**/*__g*", recursive=True):
        m = re.match(r"(.*)__g(\d+)$", os.path.basename(d))
        if not m or not os.path.exists(f"{d}/result.txt") or not os.path.exists(f"{d}/chat.jsonl"):
            continue
        steps = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
        for i, s in enumerate(steps):
            s["_img"] = f"{d}/step_{i}.png"  # what the model saw at step i (if the step has a screenshot)
        if steps:
            task = f"{os.path.basename(root)}:{m.group(1)}"
            groups.setdefault(task, {})[int(m.group(2))] = (float(open(f"{d}/result.txt").read()), steps)

samples, used = [], 0
for task, g in groups.items():
    rs = [r for r, _ in g.values()]
    if len(rs) < 2 or st.pstdev(rs) < 1e-6:
        continue
    mu, sd = st.mean(rs), st.pstdev(rs)
    used += 1
    for r, steps in g.values():
        samples += [dict(msgs=s["messages"], resp=s["response"], adv=(r - mu) / (sd + 1e-4), img=s["_img"]) for s in steps]


def has_image(msgs):
    return any(isinstance(m.get("content"), list) and any(c.get("type") == "image" for c in m["content"]) for m in msgs)


n_img = sum(has_image(s["msgs"]) for s in samples)
missing = [s for s in samples if has_image(s["msgs"]) and not os.path.exists(s["img"])]
samples = [s for s in samples if not (has_image(s["msgs"]) and not os.path.exists(s["img"]))]
print(f"screenshot steps {n_img}, skipped for a missing image (step 0) {len(missing)}")
all_r = [r for g in groups.values() for r, _ in g.values()]
print(f"groups {len(groups)} (used {used}, zero-variance {len(groups) - used}); rollouts {len(all_r)}, "
      f"mean reward {st.mean(all_r) if all_r else float('nan'):.3f}; step samples {len(samples)}")
if a.dry or not samples:  # no samples -> no adapter written, which osw_loop.py reads as "stop"
    raise SystemExit(0)
if a.max_samples:
    random.shuffle(samples)
    samples = samples[:a.max_samples]

# ---------------------------------------------------------------- model

import io
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor, AutoTokenizer
from peft import LoraConfig, PeftModel, get_peft_model

tok = AutoTokenizer.from_pretrained(a.base)
proc = AutoProcessor.from_pretrained(a.base)
# data parallel under torchrun (--nproc_per_node N): each rank takes every N-th sample of each pass, gradients are summed
# across ranks before the step, so the update equals the single-GPU one. Plain `python train_grpo.py` = 1 rank, as before.
RANK, WORLD = int(os.environ.get("RANK", 0)), int(os.environ.get("WORLD_SIZE", 1))
LOCAL = int(os.environ.get("LOCAL_RANK", 0))
torch.cuda.set_device(LOCAL)
if WORLD > 1:
    import torch.distributed as dist
    dist.init_process_group("nccl")
model = AutoModelForImageTextToText.from_pretrained(a.base, torch_dtype=torch.bfloat16, device_map={"": LOCAL})
model.gradient_checkpointing_enable()
model.enable_input_require_grads()
model.config.use_cache = False
if a.init_adapter:
    model = PeftModel.from_pretrained(model, a.init_adapter, is_trainable=True)
else:  # language-model linears only; the vision tower has same-named modules
    targets = r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)"
    model = get_peft_model(model, LoraConfig(r=a.lora_r, lora_alpha=2 * a.lora_r, target_modules=targets,
                                             lora_dropout=0.0, task_type="CAUSAL_LM"))
model.print_trainable_parameters()
eos = tok.convert_tokens_to_ids("<|im_end|>")

def shot(path):
    """The screenshot as the agent sent it: RGB, longest side --shot-px, JPEG quality 85."""
    im = Image.open(path).convert("RGB")
    im.thumbnail((a.shot_px, a.shot_px))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return Image.open(io.BytesIO(buf.getvalue())).convert("RGB")


def encode(s):
    """-> (prompt ids, vision inputs or {}). Text-only steps go through the tokenizer as before."""
    if not has_image(s["msgs"]):
        prompt = tok.apply_chat_template(s["msgs"], add_generation_prompt=True, tokenize=False)
        return tok(prompt, add_special_tokens=False)["input_ids"], {}
    img = shot(s["img"])
    # the processor wants every message's content as a list of parts (the system prompt is a plain string)
    msgs = [dict(m, content=[dict(c, image=img) if c.get("type") == "image" else c for c in m["content"]])
            if isinstance(m.get("content"), list) else dict(m, content=[{"type": "text", "text": m.get("content") or ""}])
            for m in s["msgs"]]
    enc = proc.apply_chat_template(msgs, add_generation_prompt=True, tokenize=True, return_dict=True, return_tensors="pt")
    return enc["input_ids"][0].tolist(), {k: v for k, v in enc.items() if k in ("pixel_values", "image_grid_thw")}


data = []
for s in samples:
    pi, vis = encode(s)
    ri = tok(s["resp"], add_special_tokens=False)["input_ids"] + [eos]
    if len(pi) + len(ri) <= a.max_len:
        data.append((s if vis else pi, ri, s["adv"]))  # image samples are re-encoded on use (pixel tensors stay off RAM)
print(f"encoded {len(data)}/{len(samples)} samples (rest over {a.max_len} tokens), "
      f"{sum(1 for d in data if isinstance(d[0], dict))} with a screenshot")


def logp(src, ri, grad):
    """Per-token log-probs of response ri after the prompt (ids, or a sample re-encoded with its screenshot)."""
    pi, vis = (src, {}) if isinstance(src, list) else encode(src)
    ids = torch.tensor([pi + ri], device="cuda")
    extra = {k: v.to("cuda", dtype=torch.bfloat16 if v.is_floating_point() else v.dtype) for k, v in vis.items()}
    with torch.set_grad_enabled(grad):
        logits = model(input_ids=ids, attention_mask=torch.ones_like(ids), **extra).logits[0, len(pi) - 1:-1].float()
        return torch.log_softmax(logits, -1).gather(-1, torch.tensor(ri, device="cuda")[:, None])[:, 0]


# ---------------------------------------------------------------- update

order = list(range(len(data)))
random.shuffle(order)  # (the RNG draws the same order as before: nothing else draws in between)
mine = {i for k in range(a.minibatches) for i in order[k::a.minibatches][RANK::WORLD]}  # this rank's samples (all at 1 rank)
t0 = time.time()
model.eval()
with torch.no_grad():
    old = {i: logp(*data[i][:2], False) for i in sorted(mine)}
print(f"old logprobs {time.time() - t0:.0f}s")
model.train()
params = [p for p in model.parameters() if p.requires_grad]
opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0)
stats = []
for k in range(a.minibatches):
    mb = order[k::a.minibatches]
    ntok = sum(len(data[i][1]) for i in mb)
    loss_v, clipped, ratio_sum = 0.0, 0, 0.0
    for i in mb[RANK::WORLD]:
        src, ri, adv = data[i]
        ratio = torch.exp(logp(src, ri, True) - old[i])
        surrogate = torch.minimum(ratio * adv, torch.clamp(ratio, 1 - a.clip, 1 + a.clip) * adv)
        loss = -surrogate.sum() / ntok
        loss.backward()
        loss_v += loss.item()
        clipped += int(((ratio - 1).abs() > a.clip).sum())
        ratio_sum += ratio.sum().item()
    if WORLD > 1:  # sum the ranks' gradients (each already divided by the whole minibatch's ntok) and stats
        for p in params:
            if p.grad is None:
                p.grad = torch.zeros_like(p)
            dist.all_reduce(p.grad)
        st_t = torch.tensor([loss_v, clipped, ratio_sum], device="cuda", dtype=torch.float64)
        dist.all_reduce(st_t)
        loss_v, clipped, ratio_sum = st_t[0].item(), int(st_t[1].item()), st_t[2].item()
    grad_norm = torch.nn.utils.clip_grad_norm_(params, 1.0).item()
    opt.step()
    opt.zero_grad(set_to_none=True)
    stats.append(dict(minibatch=k, samples=len(mb), loss=loss_v, grad_norm=grad_norm,
                      clip_frac=clipped / ntok, mean_ratio=ratio_sum / ntok))
    if RANK == 0:
        print(stats[-1], flush=True)

if WORLD > 1:
    dist.barrier()
if RANK != 0:
    raise SystemExit(0)
os.makedirs(a.out, exist_ok=True)
model.save_pretrained(a.out)
json.dump(dict(args=vars(a), groups=len(groups), used=used, mean_reward=st.mean(all_r), samples=len(data),
               stats=stats, secs=time.time() - t0), open(f"{a.out}/train_stats.json", "w"), indent=1)
print(f"saved {a.out} in {time.time() - t0:.0f}s")
