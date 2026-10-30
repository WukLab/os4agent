"""(fp32 compute) Is the merged model the adapter's model? Next-token log-probs over the full prompt+answer of 3 recorded calls:
merged vs base+adapter (unmerged LoRA) vs base."""
import json, torch
from peft import PeftModel
from transformers import AutoModelForImageTextToText, AutoTokenizer
B, A, M = "Qwen/Qwen3-VL-8B-Thinking", "/root/adapters/grpo_think_reg/e2", "/root/merged/grpo_think_reg/e2"
tok = AutoTokenizer.from_pretrained(B)
P = [json.loads(l) for l in open("/root/think_prompts.jsonl")][:3]
ids = [tok(tok.apply_chat_template(m, add_generation_prompt=True, tokenize=False) + "Okay, let me look at the tree.", return_tensors="pt").input_ids.cuda() for m in P]
def lp(model):
    with torch.no_grad():
        return [torch.log_softmax(model(input_ids=x).logits[0, -512:].float(), -1).cpu() for x in ids]  # last 512 positions
load = lambda p: AutoModelForImageTextToText.from_pretrained(p, dtype=torch.float32, device_map={"": 0}).eval()
base = load(B)
lb = lp(base)
lora = PeftModel.from_pretrained(base, A).eval()
ll = lp(lora)
del lora, base; torch.cuda.empty_cache()
lm = lp(load(M))
kl = lambda p, q: float(sum((pi.exp() * (pi - qi)).sum(-1).mean() for pi, qi in zip(p, q)) / len(p))
mx = lambda p, q: float(max((pi - qi).abs().max() for pi, qi in zip(p, q)))
print(f"tokens per prompt: {[x.shape[1] for x in ids]}")
print(f"merged vs base+adapter (merge error, incl. bf16 rounding of the merged weights): KL {kl(lm, ll):.2e}, max |dlogp| {mx(lm, ll):.3f}")
print(f"base   vs base+adapter (adapter effect): KL {kl(lb, ll):.2e}, max |dlogp| {mx(lb, ll):.3f}")
print(f"merged vs base:                          KL {kl(lm, lb):.2e}, max |dlogp| {mx(lm, lb):.3f}")
