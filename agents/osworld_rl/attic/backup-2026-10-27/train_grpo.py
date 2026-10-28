"""LoRA GRPO update from logged OSWorld rollouts (text/a11y agent).   Runs on the GPU pod.
  python train_grpo.py --base mPLUG/GUI-Owl-7B --data /root/data/a11y_owl_e0 [--init-adapter DIR] --out /root/adapters/e1
Data: <data>/**/<task>__g<k>/{result.txt, chat.jsonl}; one chat.jsonl line = one policy step (messages, response).
Advantage: per task group, A = (r - mean) / (std + eps); the rollout's A is applied to EVERY step of that rollout. Groups with std == 0 are skipped.
Update: tokens of the sampled response only; PPO-style clipped ratio vs. logprobs recomputed with the pre-update policy (so K minibatch steps stay
near on-policy); no KL term (beta = 0, as in DAPO); token-level normalisation inside each minibatch."""
import argparse, glob, json, math, os, random, re, statistics as st, time
import torch

ap = argparse.ArgumentParser()
ap.add_argument("--base", required=True); ap.add_argument("--data", nargs="*", default=[]); ap.add_argument("--out", required=True)
ap.add_argument("--sft", help="jsonl of {messages, response}: plain supervised warm-up (no rewards)"); ap.add_argument("--sft-epochs", type=int, default=3)
ap.add_argument("--init-adapter"); ap.add_argument("--lr", type=float, default=5e-5); ap.add_argument("--minibatches", type=int, default=4)
ap.add_argument("--clip", type=float, default=0.2); ap.add_argument("--max-len", type=int, default=6144); ap.add_argument("--lora-r", type=int, default=16)
ap.add_argument("--max-samples", type=int, default=0, help="0 = all (cap for smoke tests)"); ap.add_argument("--seed", type=int, default=0)
ap.add_argument("--dry", action="store_true", help="build the dataset and print stats, no model")
a = ap.parse_args(); random.seed(a.seed); torch.manual_seed(a.seed)

# ---------------- data ----------------
groups = {}  # task -> {g: (reward, [step records])}
for root in a.data:
    for d in glob.glob(f"{root}/**/*__g*", recursive=True):
        m = re.match(r"(.*)__g(\d+)$", os.path.basename(d))
        if not m or not os.path.exists(f"{d}/result.txt") or not os.path.exists(f"{d}/chat.jsonl"): continue
        steps = [json.loads(l) for l in open(f"{d}/chat.jsonl")]
        if steps: groups.setdefault(f"{os.path.basename(root)}:{m.group(1)}", {})[int(m.group(2))] = (float(open(f"{d}/result.txt").read()), steps)
samples, used, skipped = [], 0, 0
for task, g in groups.items():
    rs = [r for r, _ in g.values()]
    if len(rs) < 2 or st.pstdev(rs) < 1e-6: skipped += 1; continue
    mu, sd = st.mean(rs), st.pstdev(rs); used += 1
    for k, (r, steps) in g.items():
        for s in steps: samples.append(dict(msgs=s["messages"], resp=s["response"], adv=(r - mu) / (sd + 1e-4), reward=r, task=task))
allr = [r for g in groups.values() for r, _ in g.values()]
print(f"groups {len(groups)} (used {used}, zero-variance skipped {skipped}); rollouts {len(allr)} mean reward {st.mean(allr) if allr else float('nan'):.3f}; step samples {len(samples)}")
if a.sft:
    samples = [dict(msgs=r["messages"], resp=r["response"], adv=1.0) for r in map(json.loads, open(a.sft))]; allr = [1.0]; used = skipped = 0
    print(f"SFT examples {len(samples)}")
if a.dry or not samples: raise SystemExit(0)
if a.max_samples: random.shuffle(samples); samples = samples[:a.max_samples]

# ---------------- model ----------------
from transformers import AutoTokenizer
from peft import LoraConfig, PeftModel, get_peft_model
tok = AutoTokenizer.from_pretrained(a.base)
try:
    from transformers import AutoModelForImageTextToText as AM
    model = AM.from_pretrained(a.base, torch_dtype=torch.bfloat16, device_map={"": 0})
except Exception:
    from transformers import AutoModelForCausalLM as AM
    model = AM.from_pretrained(a.base, torch_dtype=torch.bfloat16, device_map={"": 0})
model.gradient_checkpointing_enable(); model.enable_input_require_grads(); model.config.use_cache = False
if a.init_adapter: model = PeftModel.from_pretrained(model, a.init_adapter, is_trainable=True)
else:  # language-model linears only (the vision tower has same-named modules)
    pat = r".*language_model.*\.(q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj)"
    model = get_peft_model(model, LoraConfig(r=a.lora_r, lora_alpha=2 * a.lora_r, target_modules=pat if any(re.fullmatch(pat, n) for n, _ in model.named_modules()) else
                           ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"], lora_dropout=0.0, task_type="CAUSAL_LM"))
model.print_trainable_parameters()
eos = tok.convert_tokens_to_ids("<|im_end|>")

def encode(s):
    p = tok.apply_chat_template(s["msgs"], add_generation_prompt=True, tokenize=False)
    pi = tok(p, add_special_tokens=False)["input_ids"]; ri = tok(s["resp"], add_special_tokens=False)["input_ids"] + [eos]
    return pi, ri
data = []
for s in samples:
    pi, ri = encode(s)
    if len(pi) + len(ri) <= a.max_len: data.append((pi, ri, s["adv"]))
print(f"encoded {len(data)}/{len(samples)} samples (dropped {len(samples)-len(data)} over {a.max_len} tokens); "
      f"prompt tokens p50 {sorted(len(x[0]) for x in data)[len(data)//2]}, response tokens p50 {sorted(len(x[1]) for x in data)[len(data)//2]}")

def logp(pi, ri, grad):
    ids = torch.tensor([pi + ri], device="cuda"); n = len(ri)
    with torch.set_grad_enabled(grad):
        lg = model(input_ids=ids, attention_mask=torch.ones_like(ids)).logits[0, len(pi) - 1: -1].float()
        return torch.log_softmax(lg, -1).gather(-1, torch.tensor(ri, device="cuda")[:, None])[:, 0]

# ---------------- supervised warm-up (plain NLL on the response tokens) ----------------
if a.sft:
    model.train(); opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0); K = a.minibatches; t0 = time.time(); stats = []
    for ep in range(a.sft_epochs):
        order = list(range(len(data))); random.shuffle(order)
        for k in range(K):
            mb = order[k::K]; ntok = sum(len(data[i][1]) for i in mb); lv = 0.0
            for i in mb:
                pi, ri, _ = data[i]; loss = -logp(pi, ri, True).sum() / ntok; loss.backward(); lv += loss.item()
            gn = torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0).item(); opt.step(); opt.zero_grad(set_to_none=True)
            stats.append(dict(epoch=ep, minibatch=k, samples=len(mb), loss=lv, grad_norm=gn)); print(stats[-1], flush=True)
    os.makedirs(a.out, exist_ok=True); model.save_pretrained(a.out)
    json.dump(dict(args=vars(a), sft_examples=len(data), stats=stats, secs=time.time() - t0), open(f"{a.out}/train_stats.json", "w"), indent=1)
    print(f"saved SFT adapter {a.out} in {time.time()-t0:.0f}s"); raise SystemExit(0)

# ---------------- update ----------------
model.eval(); t0 = time.time()
with torch.no_grad(): old = [logp(pi, ri, False).detach() for pi, ri, _ in data]
print(f"old logprobs {time.time()-t0:.0f}s"); model.train()
opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr, weight_decay=0.0)
order = list(range(len(data))); random.shuffle(order); K = a.minibatches; stats = []
for k in range(K):
    mb = order[k::K]; ntok = sum(len(data[i][1]) for i in mb); tot = clipped = 0; ratio_sum = 0.0; loss_v = 0.0
    for i in mb:
        pi, ri, adv = data[i]; new = logp(pi, ri, True); ratio = torch.exp(new - old[i])
        sur = torch.minimum(ratio * adv, torch.clamp(ratio, 1 - a.clip, 1 + a.clip) * adv)
        loss = -sur.sum() / ntok; loss.backward(); loss_v += loss.item()
        tot += len(ri); clipped += int(((ratio - 1).abs() > a.clip).sum()); ratio_sum += ratio.sum().item()
    gn = torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0).item()
    opt.step(); opt.zero_grad(set_to_none=True)
    stats.append(dict(minibatch=k, samples=len(mb), loss=loss_v, grad_norm=gn, clip_frac=clipped / tot, mean_ratio=ratio_sum / tot))
    print(stats[-1], flush=True)
os.makedirs(a.out, exist_ok=True); model.save_pretrained(a.out)
json.dump(dict(args=vars(a), groups=len(groups), used=used, skipped=skipped, mean_reward=st.mean(allr), samples=len(data), stats=stats, secs=time.time() - t0),
          open(f"{a.out}/train_stats.json", "w"), indent=1)
print(f"saved {a.out} in {time.time()-t0:.0f}s")
