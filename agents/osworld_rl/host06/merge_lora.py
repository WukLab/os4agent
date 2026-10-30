"""Merge a GRPO LoRA adapter into its base model so vLLM can serve the policy without LoRA (LoRA serving costs ~25%
decode throughput). Training keeps using the adapter; this only makes a servable copy.

  python merge_lora.py --base Qwen/Qwen3-VL-8B-Thinking --adapter /root/adapters/<exp>/e1 --out /root/merged/<exp>/e1
"""
import argparse, glob, os, shutil, time

import torch
from huggingface_hub import snapshot_download
from peft import PeftModel
from transformers import AutoModelForImageTextToText

ap = argparse.ArgumentParser()
ap.add_argument("--base", required=True)
ap.add_argument("--adapter", required=True)
ap.add_argument("--out", required=True)
ap.add_argument("--dtype", default="bfloat16", choices=["bfloat16", "float16", "float32"],
                help="dtype of the saved weights (vLLM serves in it); the merge itself is always done in float32")
a = ap.parse_args()

t0 = time.time()
model = AutoModelForImageTextToText.from_pretrained(a.base, dtype=torch.float32, device_map={"": 0})
model = PeftModel.from_pretrained(model, a.adapter).merge_and_unload()  # W + B@A in float32: one rounding, at the save
model = model.to(getattr(torch, a.dtype))
model.config.torch_dtype = a.dtype
os.makedirs(a.out, exist_ok=True)
model.save_pretrained(a.out, safe_serialization=True)
# tokenizer, processor, chat template, generation config: the base's own files (only the weights changed)
for f in glob.glob(os.path.join(snapshot_download(a.base), "*")):
    if not f.endswith((".safetensors", ".safetensors.index.json")) and not os.path.exists(os.path.join(a.out, os.path.basename(f))):
        shutil.copy(f, a.out)
print(f"merged {a.adapter} into {a.base} -> {a.out} in {time.time() - t0:.0f}s")
