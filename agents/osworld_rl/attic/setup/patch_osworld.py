"""Idempotent: make lib_run_single save the pre-action a11y tree + click->element hit per step (and snap if A11Y_SNAP=1)."""
import sys
p = sys.argv[1] + "/lib_run_single.py"; s = open(p).read()
if "a11y_hit" in s: sys.exit(print("already patched"))
s = s.replace("from lib_results_logger import log_task_completion", "from lib_results_logger import log_task_completion\nimport gzip\nfrom a11y_hit import annotate", 1)
s = s.replace("            obs, reward, done, info = env.step(action, args.sleep_after_execution)",
"""            tree = obs.get("accessibility_tree")  # what the screen looked like BEFORE this action
            if tree:
                with gzip.open(os.path.join(example_result_dir, f"step_{step_idx + 1}_{action_timestamp}.a11y.xml.gz"), "wt") as _g:
                    _g.write(tree)
            action, a11y_hit = annotate(action, tree)
            obs, reward, done, info = env.step(action, args.sleep_after_execution)""", 1)
s = s.replace('                    "reward": reward,', '                    "a11y_hit": a11y_hit,\n                    "reward": reward,', 1)
open(p, "w").write(s); print("patched")
