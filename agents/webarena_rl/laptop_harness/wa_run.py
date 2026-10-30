"""WebArena-Verified shopping rollouts for GRPO (the OSWorld runner's counterpart). Run ON the env host (06) via run_webarena.sh.
  python wa_run.py --result_dir traces/<run>/results --model pol1 --tasks webarena_batch.json --num_envs 16 --max_steps 30
Each rollout gets a FRESH shopping site (container recreated from the image; Magento has no reset), runs the text agent in headless
Chromium, and is scored offline by webarena-verified from its HAR + final answer (binary 0/1). Layout, per rollout, same as OSWorld:
  <result_dir>/webarena/a11y/<model>/shopping/<task_id>__g<k>/
    chat.jsonl         one line per policy step (messages, response, action, rows)  <- train_grpo.py input
    result.txt         reward (0.0 / 1.0)                                          <- train_grpo.py input
    traj.jsonl         one line per executed step (step_num, action_timestamp, action, a11y_hit, url, error)
    step_<n>_<ts>.png / .a11y.txt.gz / .html.gz   page state BEFORE action n (screenshot, element rows, full DOM)
    network.har  agent_response.json  eval_result.json  recording/*.webm  runtime.log  timing.json
Env: ROLLOUTS=G (rollouts per task), ROLLOUT_TEMP, PODMAN (container cli), WA_IMAGE, WA_PORT_BASE.
Tool-call speculation (--spec tage or SPEC=tage; default off): one TAGE predictor (../toolspec) shared by all rollouts guesses each step's action
before the LLM call and learns it once parsed; shadow only (guesses are logged and scored, never executed). Per step: traj.jsonl "spec"
= {key, guesses, conf, hit1, hitk, new}; per run: <result_dir>/spec_summary.json. --spec-warm (or SPEC_WARM) = earlier runs' result dirs
whose traj.jsonl are learned first, so history from older policies carries over between epochs."""
import argparse, asyncio, datetime, gzip, json, logging, os, shlex, sys, time, urllib.request
from pathlib import Path

from openai import AsyncOpenAI
from playwright.async_api import async_playwright
from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig

from wa_agent import EXTRACT_JS, KEYMAP, WebAgent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from toolspec.online import OnlineTage

ap = argparse.ArgumentParser()
ap.add_argument("--result_dir", required=True); ap.add_argument("--model", required=True); ap.add_argument("--tasks", default="webarena_batch.json")
ap.add_argument("--num_envs", type=int, default=16); ap.add_argument("--max_steps", type=int, default=30)
ap.add_argument("--sleep_after_execution", type=float, default=1.0)
ap.add_argument("--spec", choices=["off", "tage"], default=os.environ.get("SPEC", "off")); ap.add_argument("--spec-topk", type=int, default=8)
ap.add_argument("--spec-warm", nargs="*", default=os.environ.get("SPEC_WARM", "").split()); a = ap.parse_args()

G = int(os.environ.get("ROLLOUTS", "8")); TEMP = float(os.environ.get("ROLLOUT_TEMP", "1.0"))
PODMAN = shlex.split(os.environ.get("PODMAN", "sudo env CONTAINERS_STORAGE_CONF=/mnt/ssd2/podman/storage.conf podman"))
IMAGE = os.environ.get("WA_IMAGE", "docker.io/am1n3e/webarena-verified-shopping:latest")
PORT0 = int(os.environ.get("WA_PORT_BASE", "7770"))
LOGIN = {"X-M2-Customer-Auto-Login": "emma.lopez@gmail.com:Password.123"}
LLM = AsyncOpenAI(base_url=f"http://127.0.0.1:{os.environ.get('PROXY_PORT', '8001')}/v1", api_key="x")
ts = lambda: datetime.datetime.now().strftime("%Y%m%d@%H%M%S%f")
log = logging.getLogger("wa"); logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
SPEC = OnlineTage(a.spec_topk) if a.spec == "tage" else None


def wa_for(base):
    """Scoring config for one site copy. The URL must match the origin recorded in the HAR byte for byte."""
    return WebArenaVerified(config=WebArenaVerifiedConfig(environments={
        "__SHOPPING__": {"urls": [base], "credentials": {"username": "emma.lopez@gmail.com", "password": "Password.123"}}}))


def http_ok(url, timeout=3):
    try: return urllib.request.urlopen(url, timeout=timeout).status
    except Exception: return None


async def sh(*cmd):
    p = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out = (await p.communicate())[0].decode(errors="replace")
    if p.returncode: raise RuntimeError(f"{cmd[-4:]} rc={p.returncode}: {out[-400:]}")
    return out


async def fresh_site(slot):
    """Recreate slot's container from the image -> clean DB. Returns (base url, seconds). os4agent's live clone replaces this."""
    port, name, t0 = PORT0 + 2 * slot, f"wa-shop-{slot}", time.time()
    base = f"http://localhost:{port}"
    await sh(*PODMAN, "rm", "-f", "-t", "0", name)
    await sh(*PODMAN, "run", "-d", "--name", name, "-p", f"{port}:80", "-p", f"{port + 1}:8877",
             "-e", f"WA_ENV_CTRL_EXTERNAL_SITE_URL={base}", IMAGE)
    for _ in range(600):
        st = await asyncio.to_thread(lambda: urllib.request.urlopen(f"http://localhost:{port + 1}/status", timeout=3).read() if http_ok(f"http://localhost:{port + 1}/status") else b"{}")
        if json.loads(st or b"{}").get("success") and await asyncio.to_thread(http_ok, base + "/", 30) == 200:
            return base, time.time() - t0
        await asyncio.sleep(1)
    raise RuntimeError(f"{name} not ready after 600 s")


async def page_state(page, d, n, stamp):
    """Snapshot the page BEFORE action n: element rows (+ ids injected into the DOM), screenshot, full DOM."""
    rows = await page.evaluate(EXTRACT_JS)
    await page.screenshot(path=f"{d}/step_{n}_{stamp}.png")
    with gzip.open(f"{d}/step_{n}_{stamp}.a11y.txt.gz", "wt") as f: f.write("\n".join(f'[{i}] {r} "{nm}"' for i, (r, nm, _) in enumerate(rows)))
    with gzip.open(f"{d}/step_{n}_{stamp}.html.gz", "wt") as f: f.write(await page.content())
    return rows


async def execute(ctx, pages, cur, act):
    """Run one action. Returns (current tab index, error or None)."""
    page, kind = pages[cur], act.get("action")
    loc = lambda: page.locator(f'[data-wa="{int(act["id"])}"]').first
    before = len(ctx.pages)
    if kind == "click": await loc().click(timeout=5000)
    elif kind == "type":
        t = str(act.get("text", "")); await loc().fill(t.rstrip("\n"), timeout=5000)
        if t.endswith("\n"): await loc().press("Enter")
    elif kind == "select":
        try: await loc().select_option(label=str(act.get("option")), timeout=5000)
        except Exception: await loc().select_option(value=str(act.get("option")), timeout=5000)
    elif kind == "key": await page.keyboard.press("+".join(KEYMAP.get(str(k).lower(), str(k)) for k in act.get("keys", [])))
    elif kind == "scroll": await page.mouse.wheel(0, -600 if act.get("direction") == "up" else 600)
    elif kind == "goto": await page.goto(str(act["url"]), timeout=30000)
    elif kind == "go_back": await page.go_back(timeout=30000)
    elif kind == "tab":
        i = int(act.get("index", cur))
        if not 0 <= i < len(ctx.pages): raise ValueError(f"no tab {i}")
        cur = i; await ctx.pages[cur].bring_to_front()
    elif kind in ("wait", "invalid"): await asyncio.sleep(1)
    else: raise ValueError(f"unknown action {kind}")
    if len(ctx.pages) > before: cur = len(ctx.pages) - 1   # click opened a new tab -> follow it
    try: await ctx.pages[cur].wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception: pass
    return cur


async def rollout(pw, slot, task, g):
    d = Path(a.result_dir) / "webarena" / "a11y" / a.model / "shopping" / f"{task.task_id}__g{g}"
    if (d / "result.txt").exists(): return
    d.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(d / "runtime.log"); rl = logging.getLogger(str(d)); rl.addHandler(fh); rl.setLevel(logging.INFO)
    timing = {"t_start": time.time()}
    base, timing["reset_s"] = await fresh_site(slot)
    wa = wa_for(base); urls = wa.config.render_url([str(u) for u in task.start_urls], sites=task.sites)
    urls = urls if isinstance(urls, list) else [urls]
    rl.info(f"slot {slot} site {base} ready in {timing['reset_s']:.1f}s; task {task.task_id}: {task.intent}; start {urls}")
    browser = await pw.chromium.launch(headless=True)
    ctx = await browser.new_context(record_har_path=str(d / "network.har"), record_har_content="embed", extra_http_headers=LOGIN,
                                    viewport={"width": 1280, "height": 900}, record_video_dir=str(d / "recording"))
    answer, steps = None, 0
    try:
        pages = [await ctx.new_page() for _ in urls]
        for p, u in zip(pages, urls): await p.goto(u, timeout=60000); await p.reload(timeout=60000)   # auto-login applies from the 2nd request
        cur = 0; await pages[0].bring_to_front()
        agent = WebAgent(LLM, a.model, task.intent, str(d / "chat.jsonl"), temperature=TEMP)
        timing["t_active"] = time.time()
        for n in range(1, a.max_steps + 1):
            page = ctx.pages[cur]; stamp = ts()
            rows = await page_state(page, d, n, stamp)
            tabs = [f"{await p.title()} ({p.url})" for p in ctx.pages]
            if SPEC: SPEC.decide(task.task_id, str(d))   # guess this step's action before the LLM is asked
            resp, act = await agent.predict(tabs, cur, page.url, rows)
            hit = rows[act["id"]] if isinstance(act.get("id"), int) and 0 <= act["id"] < len(rows) else None
            rec = {"step_num": n, "action_timestamp": stamp, "action": json.dumps(act), "url": page.url, "response": resp,
                   "a11y_hit": {"role": hit[0], "name": hit[1], "key": f"{hit[0]}|{hit[1][:60]}"} if hit else None, "reward": 0, "done": False}
            if SPEC and (sp := SPEC.reveal(task.task_id, str(d), act, rec["a11y_hit"])): rec["spec"] = sp   # score the guess, learn the action
            steps = n
            if act.get("action") == "done":
                answer = act.get("answer"); rec["done"] = True
            else:
                try: cur = await execute(ctx, ctx.pages, cur, act)
                except Exception as e: rec["error"] = repr(e)[:300]   # bad id / timeout = wasted step, logged
                await asyncio.sleep(a.sleep_after_execution)
            with open(d / "traj.jsonl", "a") as f: f.write(json.dumps(rec) + "\n")
            rl.info(f"step {n}: {rec['action']}{' ERR ' + rec['error'] if 'error' in rec else ''}")
            if rec["done"]: break
    except Exception as e:
        rl.exception(f"rollout crashed: {e!r}")
    finally:
        timing["t_end"] = time.time()
        await ctx.close(); await browser.close()   # HAR is written on context close
    if answer is None:
        answer = {"task_type": "RETRIEVE", "status": "UNKNOWN_ERROR", "retrieved_data": None, "error_details": f"no answer after {steps} steps"}
    (d / "agent_response.json").write_text(json.dumps(answer))
    try:
        r = wa.evaluate_task(task_id=task.task_id, agent_response=answer, network_trace=d / "network.har")
        reward = float(r.score); (d / "eval_result.json").write_text(r.model_dump_json(indent=1))
    except Exception as e:
        reward = 0.0; rl.exception(f"eval failed: {e!r}")
    (d / "result.txt").write_text(str(reward))
    timing.update(steps=steps, reward=reward, eval_s=time.time() - timing["t_end"]); (d / "timing.json").write_text(json.dumps(timing))
    rl.info(f"reward {reward} after {steps} steps; reset {timing['reset_s']:.1f}s active {timing['t_end'] - timing.get('t_active', timing['t_end']):.1f}s")
    log.info(f"[slot {slot}] {task.task_id}__g{g}: reward {reward} steps {steps}")
    rl.removeHandler(fh); fh.close()


async def main():
    batch = json.load(open(a.tasks))
    ids = batch["shopping"] if isinstance(batch, dict) else batch
    wa0 = wa_for(f"http://localhost:{PORT0}")
    tasks = {t.task_id: t for t in wa0.get_tasks()}
    queue = asyncio.Queue()
    for tid in ids:   # group-major, like the OSWorld runner with ROLLOUTS=G
        for g in range(G): queue.put_nowait((tasks[int(tid)], g))
    log.info(f"{queue.qsize()} rollouts ({len(ids)} tasks x {G}) on {a.num_envs} site slots, model {a.model}")
    if SPEC and a.spec_warm: log.info(f"spec: TAGE warmed with {SPEC.warm(a.spec_warm)} actions from {a.spec_warm}")

    async def worker(slot):
        while not queue.empty():
            task, g = queue.get_nowait()
            try: await rollout(pw, slot, task, g)
            except Exception as e: log.exception(f"[slot {slot}] {task.task_id}__g{g} failed: {e!r}")
        await sh(*PODMAN, "rm", "-f", "-t", "0", f"wa-shop-{slot}")

    async with async_playwright() as pw:
        await asyncio.gather(*(worker(s) for s in range(a.num_envs)))
    log.info("all rollouts done")
    if SPEC:
        s = SPEC.summary(); (Path(a.result_dir) / "spec_summary.json").write_text(json.dumps({"warm": a.spec_warm, **s}, indent=1))
        log.info(f"spec: TAGE hit@1 {s['hit1_pct']:.1f}% hit@{a.spec_topk} {s[f'hit{a.spec_topk}_pct']:.1f}% (new actions hit@1 {s['new_hit1_pct']:.1f}%) over {s['decisions']} actions")


asyncio.run(main())
