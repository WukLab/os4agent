"""fp32 compute: merge error of merged copies (saved in different dtypes) vs base+adapter, next to the adapter's effect.
python merge_check3.py MERGED_DIR..."""
import json, sys, torch
from peft import PeftModel
from transformers import AutoModelForImageTextToText, AutoTokenizer
B, A = "Qwen/Qwen3-VL-8B-Thinking", "/root/adapters/grpo_think_reg/e2"
tok = AutoTokenizer.from_pretrained(B)
P = [json.loads(l) for l in open("/root/think_prompts.jsonl")][:3]
ids = [tok(tok.apply_chat_template(m, add_generation_prompt=True, tokenize=False) + "Okay, let me look at the tree.", return_tensors="pt").input_ids.cuda() for m in P]
def lp(model):
    with torch.no_grad():
        return [torch.log_softmax(model(input_ids=x).logits[0, -512:].float(), -1).cpu() for x in ids]
load = lambda p: AutoModelForImageTextToText.from_pretrained(p, dtype=torch.float32, device_map={"": 0}).eval()
kl = lambda p, q: float(sum((pi.exp() * (pi - qi)).sum(-1).mean() for pi, qi in zip(p, q)) / len(p))
base = load(B); lb = lp(base)
lora = PeftModel.from_pretrained(base, A).eval(); ll = lp(lora)
del lora, base; torch.cuda.empty_cache()
print(f"adapter effect, base vs base+adapter: KL {kl(lb, ll):.2e}")
for m in sys.argv[1:]:
    model = load(m); lm = lp(model); del model; torch.cuda.empty_cache()
    print(f"{m}: merge error KL {kl(lm, ll):.2e} ({100 * kl(lm, ll) / kl(lb, ll):.0f}% of the adapter effect), vs base {kl(lm, lb):.2e}")
