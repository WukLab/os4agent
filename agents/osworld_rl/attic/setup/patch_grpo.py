"""Idempotent runner patches.  python patch_grpo.py <OSWorld dir>
 ROLLOUTS=G       repeats each task G times (group-major, result dir <id>__g<k>)
 ROLLOUT_TEMP     sampling temperature (NOT named TEMP: Node/playwright read TEMP as its tmp dir)
 PROMPT_STYLE     e.g. qwen2vl_no_thought -> the model answers with Action only (no Thought tokens)
 ENABLE_PROXY=1   use OSWorld's proxy pool for proxy:true tasks (off by default: its apt-get update hangs, VMs reach the web directly)"""
import sys
p = sys.argv[1] + "/scripts/python/run_multienv_uitars15_v1.py"; s = open(p).read()
if "ROLLOUTS" not in s:
    s = s.replace("            all_tasks.append((domain, example_id))",
    "            all_tasks += [(domain, example_id, g) for g in range(int(os.environ.get('ROLLOUTS', '1')))]", 1)
    s = s.replace("            domain, example_id = item\n", "            domain, example_id, g = item\n", 1)
    s = s.replace("                    domain,\n                    example_id,\n                )",
    "                    domain,\n                    example_id if int(os.environ.get('ROLLOUTS', '1')) == 1 else f'{example_id}__g{g}',\n                )", 1)
    s = s.replace('"temperature": 0.0,', '"temperature": float(os.environ.get("ROLLOUT_TEMP", "0.0")),')
    print("patched rollouts/temperature")
if "PROMPT_STYLE" not in s:
    s = s.replace('"prompt_style": "qwen25vl_normal",', '"prompt_style": os.environ.get("PROMPT_STYLE", "qwen25vl_normal"),', 1)
    print("patched PROMPT_STYLE")
if "ENABLE_PROXY" not in s:
    s = s.replace("enable_proxy=True,", "enable_proxy=os.environ.get('ENABLE_PROXY') == '1',", 1)
    print("patched ENABLE_PROXY")
open(p, "w").write(s)
