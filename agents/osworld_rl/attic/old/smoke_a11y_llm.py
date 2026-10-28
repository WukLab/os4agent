"""Does the served model answer a11y prompts in our action format?   (run in the osworld dir, tunnel up)
DOUBAO_API_URL=http://127.0.0.1:8000/v1 python smoke_a11y_llm.py traces/<run> <served-model> [n=12]"""
import glob, gzip, json, os, sys
sys.path.insert(0, "OSWorld")
from mm_agents.a11y_owl_agent import A11yAgent, parse
run, model, n = sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 12
ag = A11yAgent(model=model, temperature=1.0); ok = tot = shown = 0
for d in sorted(glob.glob(f"{run}/results/*/*/*/*/*__g0"))[:n]:
    task = os.path.basename(d)[:-4]
    t = json.loads(open(d + "/traj.jsonl").readline())
    ex = glob.glob(f"OSWorld/evaluation_examples/examples/*/{task}.json")
    if not ex: continue
    instr = json.load(open(ex[0]))["instruction"]
    tree = gzip.open(f"{d}/step_{t['step_num']}_{t['action_timestamp']}.a11y.xml.gz", "rt").read()
    resp, code = ag.predict(instr, {"accessibility_tree": tree}); tot += 1
    try: parse(resp); ok += code[0] != "WAIT"
    except Exception: pass
    if shown < 4: print("TASK:", instr[:100]); print("  RESP:", resp[:240].replace("\n", " | ")); print("  CODE:", code[0][:100].replace("\n", " ; ")); shown += 1
print(f"valid action parsed {ok}/{tot}")
