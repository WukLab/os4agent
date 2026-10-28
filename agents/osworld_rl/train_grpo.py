"""One LoRA GRPO update from logged OSWorld rollouts. Runs on the GPU pod.

  python train_grpo.py --base Qwen/Qwen3-VL-8B-Instruct --data /root/data/<run> [--init-adapter DIR] --out /root/adapters/e1

Data: <data>/**/<task>__g<k>/{result.txt, chat.jsonl}; each chat.jsonl line is one policy step (messages, response).
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
        samples += [dict(msgs=s["messages"], resp=s["response"], adv=(r - mu) / (sd + 1e-4)) for s in steps]
all_r = [r for g in groups.values() for r, _ in g.values()]
print(f"groups {len(groups)} (used {used}, zero-variance {len(groups) - used}); rollouts {len(all_r)}, "
      f"mean reward {st.mean(all_r) if all_r else float('nan'):.3f}; step samples {len(samples)}")
if a.dry or not samples:  # no samples -> no adapter written, which osw_loop.py reads as "stop"
    raise SystemExit(0)
if a.max_samples:
    random.shuffle(samples)
    samples = samples[:a.max_samples]

# ---------------------------------------------------------------- model

from transformers import AutoModelForImageTextToText, AutoTokenizer
from peft import LoraConfig, PeftModel, get_peft_model

tok = AutoTokenizer.from_pretrained(a.base)
model = AutoModelForImageTextToText.from_pretrained(a.base, torch_dtype=torch.bfloat16, device_map={"": 0})
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

data = []
for s in samples:
    prompt = tok.apply_chat_template(s["msgs"], add_generation_prompt=True, tokenize=False)
    pi = tok(prompt, add_special_tokens=False)["input_ids"]
    ri = tok(s["resp"], add_special_tokens=False)["input_ids"] + [eos]
    if len(pi) + len(ri) <= a.max_len:
        data.append((pi, ri, s["adv"]))
print(f"encoded {len(data)}/{len(samples)} samples (rest over {a.max_len} tokens)")


def logp(pi, ri, grad):
    """Per-token log-probs of response ri after prompt pi."""
    ids = torch.tensor([pi + ri], device="cuda")
    with torch.set_grad_enabled(grad):
        logits = model(input_ids=ids, attention_mask=torch.ones_like(ids)).logits[0, len(pi) - 1:-1].float()
        return torch.log_softmax(logits, -1).gather(-1, torch.tensor(ri, device="cuda")[:, None])[:, 0]


# ---------------------------------------------------------------- update

t0 = time.time()
model.eval()
with torch.no_grad():
    old = [logp(pi, ri, False) for pi, ri, _ in data]
print(f"old logprobs {time.time() - t0:.0f}s")
model.train()
params = [p for p in model.parameters() if p.requires_grad]
opt = torch.optim.AdamW(params, lr=a.lr, weight_decay=0.0)
order = list(range(len(data)))
random.shuffle(order)
stats = []
for k in range(a.minibatches):
    mb = order[k::a.minibatches]
    ntok = sum(len(data[i][1]) for i in mb)
    loss_v, clipped, ratio_sum = 0.0, 0, 0.0
    for i in mb:
        pi, ri, adv = data[i]
        ratio = torch.exp(logp(pi, ri, True) - old[i])
        surrogate = torch.minimum(ratio * adv, torch.clamp(ratio, 1 - a.clip, 1 + a.clip) * adv)
        loss = -surrogate.sum() / ntok
        loss.backward()
        loss_v += loss.item()
        clipped += int(((ratio - 1).abs() > a.clip).sum())
        ratio_sum += ratio.sum().item()
    grad_norm = torch.nn.utils.clip_grad_norm_(params, 1.0).item()
    opt.step()
    opt.zero_grad(set_to_none=True)
    stats.append(dict(minibatch=k, samples=len(mb), loss=loss_v, grad_norm=grad_norm,
                      clip_frac=clipped / ntok, mean_ratio=ratio_sum / ntok))
    print(stats[-1], flush=True)

os.makedirs(a.out, exist_ok=True)
model.save_pretrained(a.out)
json.dump(dict(args=vars(a), groups=len(groups), used=used, mean_reward=st.mean(all_r), samples=len(data),
               stats=stats, secs=time.time() - t0), open(f"{a.out}/train_stats.json", "w"), indent=1)
print(f"saved {a.out} in {time.time() - t0:.0f}s")
