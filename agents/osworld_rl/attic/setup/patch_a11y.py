"""Idempotent: AGENT=a11y makes the UI-TARS runner use mm_agents/a11y_owl_agent.A11yAgent.  python patch_a11y.py <OSWorld dir>"""
import shutil, sys
d = sys.argv[1]; shutil.copy(__file__.replace("patch_a11y.py", "a11y_owl_agent.py"), f"{d}/mm_agents/a11y_owl_agent.py")
p = f"{d}/scripts/python/run_multienv_uitars15_v1.py"; s = open(p).read()
if "A11yAgent" in s: sys.exit(print("already patched"))
old = "        agent = UITARSAgent("
new = '''        if os.environ.get("AGENT") == "a11y":
            from mm_agents.a11y_owl_agent import A11yAgent
            agent = A11yAgent(model=args.model, temperature=float(os.environ.get("ROLLOUT_TEMP", "1.0")))
        else:
          agent = UITARSAgent('''
assert old in s; s = s.replace(old, new, 1)
# the original call continues on the following lines; indent them to stay inside the else block
i = s.index(new) + len(new); j = s.index("        )\n", i) + len("        )\n")
body = s[i:j].replace("\n", "\n  ")[:-2] if False else s[i:j]
s = s[:i] + "".join("  " + l if k else l for k, l in enumerate(body.splitlines(True))) + s[j:]
open(p, "w").write(s); print("patched")
