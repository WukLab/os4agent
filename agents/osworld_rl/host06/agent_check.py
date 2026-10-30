"""One real A11yAgent.predict through the tunnel with the Thinking budget (A11Y_REASON=1 A11Y_THINK_BUDGET set by caller)."""
import json, os, sys, time
sys.argv = ["x"]
import a11y_owl_agent as A
p = json.load(open(sys.stdin.fileno()))  # recorded Calc prompt messages
xml = None
ag = A.A11yAgent(os.environ["MODEL"])
# reuse a recorded Calc step's messages directly: monkeypatch linearize input by calling the client path with recorded msgs
msgs = p["messages"]
ag.reset()
class Obs(dict): pass
t0 = time.time()
r = ag.client.chat.completions.create(model=ag.model, messages=[{"role": "system", "content": A.SYSTEM}, msgs[1]],
                                      temperature=1.0, top_p=0.9, max_tokens=A.THINK_BUDGET)
resp = r.choices[0].message.content or ""
forced = "</think>" not in resp
if forced:
    resp += A.THINK_CLOSE
    r2 = ag.client.chat.completions.create(model=ag.model, messages=[{"role": "system", "content": A.SYSTEM}, msgs[1], {"role": "assistant", "content": resp}],
                                           temperature=1.0, top_p=0.9, max_tokens=300, extra_body={"add_generation_prompt": False, "continue_final_message": True})
    resp += r2.choices[0].message.content or ""
print(f"budget {A.THINK_BUDGET}, forced={forced}, {time.time() - t0:.1f} s, action: {A.parse(resp.rsplit('</think>', 1)[-1])}")
