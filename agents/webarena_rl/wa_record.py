"""Record WebArena-Lite shopping rollouts with full timing, no snapshot / fork: every rollout gets its own freshly set-up
environment (wa-shop-orig-browser: site + in-container Chromium) under podman on the NVMe btrfs. Runs as root.
  sudo -n env LLM_URL=http://127.0.0.1:8100/v1 /mnt/data/ssd1/yutong_data/venv-pw1.44.0/bin/python wa_record.py \
      --result-dir /mnt/data/btrfs/wa_traces/<run> [--groups-at-once 4] [--rollouts 8] [--tasks 29,31,...]
Waves of --groups-at-once task groups (× --rollouts each = the batch): set up every environment of the wave
(--setup-concurrency at a time), then start all rollouts together (one synchronous GRPO batch), tear down, next wave.
Agent: the teammate's text agent (~/RL-tool-spec/webarena/wa_agent.py: SYSTEM prompt, element rows, parse; actions as
wa_run.py's execute), with the model call streamed so time-to-first-token is separate from decode.
Outputs in --result-dir:
  config.json, events.jsonl (run / wave / setup / rollout events), mem.jsonl (every --sample-s: per environment PSS
  split + RSS + cgroup memory.current/stat, host used memory), vllm.jsonl (the server's running / waiting requests and
  KV-cache use, every --sample-s), rtt.jsonl (GET /v1/models round trip, every 30 s),
  <task>__g<k>/steps.jsonl (one line per step: observation, model call, action, settle times; tokens; action; URLs;
  error), chat.jsonl (messages, response, action, rows: what replay needs), result.json (answer, reward, setup timing).
Scoring: lite_eval.py (the 32 tasks need no LLM judge). The agent's Verified-style answer is turned into Lite's plain
string: retrieved_data items joined with ', ' (or the status when there are none)."""
import argparse, asyncio, json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path

from openai import AsyncOpenAI
from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(Path("/home/yutong/RL-tool-spec/webarena"))]
import lite_eval  # noqa: E402
from wa_agent import EXTRACT_JS, HISTORY, KEYMAP, SYSTEM, linearize, parse  # noqa: E402  (teammate's agent, unchanged)

DEFAULT_TASKS = "29,31,36,37,41,46,56,58,65,66,67,68,72,74,76,77,78,82,86,93,94,95,103,104,109,118,119,120,121,129,148,162"
ap = argparse.ArgumentParser()
ap.add_argument("--result-dir", required=True)
ap.add_argument("--tasks", default=DEFAULT_TASKS, help="Lite task ids (default: 32 non-fuzzy shopping tasks, seed 0)")
ap.add_argument("--rollouts", type=int, default=8)
ap.add_argument("--groups-at-once", type=int, default=4, help="task groups per wave; batch = this x --rollouts")
ap.add_argument("--max-steps", type=int, default=15)
ap.add_argument("--setup-concurrency", type=int, default=8)
ap.add_argument("--sleep-after-action", type=float, default=1.0, help="wa_run.py's sleep_after_execution")
ap.add_argument("--llm-url", default=os.environ.get("LLM_URL", "http://127.0.0.1:8100/v1"))
ap.add_argument("--model", default="qwen3vl8b")
ap.add_argument("--temperature", type=float, default=1.0)
ap.add_argument("--max-tokens", type=int, default=512)
ap.add_argument("--stream", type=int, default=1, help="0 for a non-streaming mock server")
ap.add_argument("--sample-s", type=float, default=5.0, help="memory sampling interval")
ap.add_argument("--vllm-sample-s", type=float, default=1.0, help="vLLM /metrics interval (a request lasts ~0.5 s)")
ap.add_argument("--image", default="localhost/wa-shop-orig-browser:latest")
ap.add_argument("--limit-waves", type=int, default=0, help="stop after this many waves (pilot)")
ap.add_argument("--only", default="", help="re-record just these rollouts: task:k,task:k,... (all in one wave)")
a = ap.parse_args()

REPO = HERE.parent.parent
PODMAN = ["env", "CONTAINERS_STORAGE_CONF=/mnt/data/btrfs/podman/storage.conf",
          f"CONTAINERS_CONF={HERE}/containers-os4agent.conf", str(REPO / "podman-tfork.sh")]
MYSQL = ["mysql", "-u", "magentouser", "-pMyPassword", "magentodb", "-e"]
OUT = Path(a.result_dir)
OUT.mkdir(parents=True, exist_ok=True)
TASKS = lite_eval.load_tasks()
RUN = OUT.name.replace("_", "-")[:30]
LLM = AsyncOpenAI(base_url=a.llm_url, api_key="x", timeout=1800)
LIVE = {}          # container name -> (init pid, group label)
KILLED = []        # killed (not yet removed) containers of finished waves
ONLY = {}          # --only: task id -> [rollout indices]
for _x in filter(None, a.only.split(",")):
    ONLY.setdefault(int(_x.split(":")[0]), []).append(int(_x.split(":")[1]))
SETUP_SEM = asyncio.Semaphore(a.setup_concurrency)


def now():
    return time.time()


def jl(path, rec):
    with open(path, "a") as f:
        f.write(json.dumps(rec) + "\n")


def event(kind, **kw):
    rec = {"t": now(), "event": kind, **kw}
    print(json.dumps(rec)[:300], flush=True)
    jl(OUT / "events.jsonl", rec)


async def pod(*args, check=True, timeout=900):
    p = await asyncio.create_subprocess_exec(*PODMAN, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(p.communicate(), timeout)
    except asyncio.TimeoutError:
        p.kill()
        raise RuntimeError(f"podman {' '.join(args[:3])} timed out")
    if check and p.returncode:
        raise RuntimeError(f"podman {' '.join(args[:3])}: rc={p.returncode} {err.decode()[-800:]}")
    return out.decode().strip()


# ---------------------------------------------------------------- memory, vLLM metrics, RTT samplers

def smaps(pids):
    tot = dict.fromkeys(("Rss", "Pss", "Pss_Anon", "Pss_File", "Pss_Shmem"), 0)
    for pid in pids:
        try:
            for line in open(f"/proc/{pid}/smaps_rollup"):
                k, _, v = line.partition(":")
                if k in tot:
                    tot[k] += int(v.split()[0])
        except (OSError, ValueError):
            pass
    return {f"{k.lower()}_mib": round(v / 1024, 1) for k, v in tot.items()}


def cgroup(pid):
    d = "/sys/fs/cgroup" + open(f"/proc/{pid}/cgroup").read().strip().split("::", 1)[1]
    st = {l.split()[0]: int(l.split()[1]) for l in open(f"{d}/memory.stat")}
    cur = int(open(f"{d}/memory.current").read())
    return {"cg_mib": round(cur / 2**20, 1), "cg_ws_mib": round((cur - st.get("inactive_file", 0)) / 2**20, 1),
            **{f"cg_{k}_mib": round(st.get(k, 0) / 2**20, 1) for k in ("anon", "file", "shmem", "kernel")}}


async def sample_memory():
    while True:
        try:
            ns = {}
            for p in filter(str.isdigit, os.listdir("/proc")):
                try:
                    ns.setdefault(os.readlink(f"/proc/{p}/ns/pid"), []).append(int(p))
                except OSError:
                    pass
            per = {}
            for name, (pid, grp) in list(LIVE.items()):
                try:
                    per[name] = {**smaps(ns.get(os.readlink(f"/proc/{pid}/ns/pid"), [])), **cgroup(pid), "group": grp}
                except OSError:
                    pass
            m = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
            tot = {k: round(sum(c.get(k, 0) for c in per.values()), 1) for k in ("pss_mib", "rss_mib", "cg_mib", "cg_ws_mib")}
            jl(OUT / "mem.jsonl", {"t": now(), "envs": len(per), "total": tot, "containers": per,
                                   "host": {"used_mib": (m["MemTotal"] - m["MemAvailable"]) // 1024, "cached_mib": m["Cached"] // 1024,
                                            "anon_mib": m["AnonPages"] // 1024}, "load1": os.getloadavg()[0]})
        except Exception as e:
            print("mem sampler:", e, flush=True)
        await asyncio.sleep(a.sample_s)


METRICS = re.compile(r"^(vllm:(?:num_requests_running|num_requests_waiting|gpu_cache_usage_perc|kv_cache_usage_perc|"
                     r"num_preemptions_total|prompt_tokens_total|generation_tokens_total))(?:\{[^}]*\})? ([0-9.e+-]+)$", re.M)


async def sample_vllm():
    base = a.llm_url.rsplit("/v1", 1)[0]
    while True:
        try:
            t0 = now()
            txt = await asyncio.to_thread(lambda: urllib.request.urlopen(base + "/metrics", timeout=10).read().decode())
            jl(OUT / "vllm.jsonl", {"t": t0, **{k: float(v) for k, v in METRICS.findall(txt)}})
        except Exception:
            pass
        await asyncio.sleep(a.vllm_sample_s)


async def sample_rtt():
    while True:
        try:
            t0 = now()
            await asyncio.to_thread(lambda: urllib.request.urlopen(a.llm_url + "/models", timeout=30).read())
            jl(OUT / "rtt.jsonl", {"t": t0, "rtt_s": round(now() - t0, 4)})
        except Exception as e:
            jl(OUT / "rtt.jsonl", {"t": now(), "error": repr(e)[:200]})
        await asyncio.sleep(30)


# ---------------------------------------------------------------- environment

async def setup_env(name, task, label):
    """Fresh environment: container, MySQL, base URL + cache flush, first page, CDP, login, start URL(s). -> timing"""
    tm = {"t_start": now()}
    async with SETUP_SEM:
        tm["t_setup_slot"] = now()
        await pod("rm", "-f", "-t", "0", name, check=False)
        await pod("run", "-d", "--name", name, "--cgroupns=host", "--ulimit", "nofile=1048576:1048576", "--security-opt",
                  "seccomp=unconfined", "--security-opt", "label=disable", "--shm-size=2g", a.image)
        tm["t_container_up"] = now()
        r = json.loads(await pod("inspect", name))[0]
        LIVE[name] = (r["State"]["Pid"], label)
        ip = r["NetworkSettings"]["IPAddress"]
        for _ in range(300):   # wait for MySQL inside the container
            p = await asyncio.create_subprocess_exec(*PODMAN, "exec", name, *MYSQL, "select 1",
                                                     stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            if await p.wait() == 0:
                break
            await asyncio.sleep(2)
        tm["t_mysql_up"] = now()
        await pod("exec", name, "/var/www/magento2/bin/magento", "setup:store-config:set", "--base-url=http://localhost/")
        await pod("exec", name, *MYSQL, "UPDATE core_config_data SET value='http://localhost/' WHERE path = 'web/secure/base_url';")
        await pod("exec", name, "/var/www/magento2/bin/magento", "cache:flush")
        tm["t_base_url_done"] = now()
        code = await pod("exec", name, "curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "300",
                         "http://localhost/", check=False)
        tm["t_first_page"], tm["first_page_http"] = now(), code
    return ip, tm


async def open_browser(pw, ip, task, tm):
    for _ in range(60):
        try:
            br = await pw.chromium.connect_over_cdp(f"http://{ip}:9222", timeout=20_000)
            break
        except Exception:
            await asyncio.sleep(2)
    else:
        raise RuntimeError(f"no CDP at {ip}")
    tm["t_cdp"] = now()
    ctx = br.contexts[0]
    page = ctx.pages[0] if ctx.pages else await ctx.new_page()
    await page.set_viewport_size({"width": 1280, "height": 900})
    await page.goto("http://localhost/customer/account/login/", timeout=120_000)
    await page.fill("#email", "emma.lopez@gmail.com")
    await page.fill("#pass", "Password.123")
    await page.click("#send2", timeout=60_000)
    await page.wait_for_load_state("load", timeout=120_000)
    tm["t_login_done"] = now()
    urls = [u.strip().replace("__SHOPPING__", lite_eval.SHOPPING) for u in task["start_url"].split("|AND|")]
    pages = [page] + [await ctx.new_page() for _ in urls[1:]]
    for pg, u in zip(pages, urls):
        await pg.goto(u, timeout=120_000)
    await pages[0].bring_to_front()
    tm["t_ready"] = now()
    return br, ctx


async def execute(ctx, cur, act):
    """wa_run.py's execute, unchanged. -> current tab index"""
    page, kind = ctx.pages[cur], act.get("action")
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
    if len(ctx.pages) > before: cur = len(ctx.pages) - 1
    return cur


async def read_page(page, ctx, tries=3):
    """EXTRACT_JS rows + tab titles; retried when the page is mid-navigation ("Execution context was destroyed")."""
    for i in range(tries):
        try:
            rows = await page.evaluate(EXTRACT_JS)
            return rows, [f"{await p.title()} ({p.url})" for p in ctx.pages]
        except Exception as e:
            if i == tries - 1 or "context was destroyed" not in str(e):
                raise
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception:
                pass


def lite_answer(act):
    ans = act.get("answer")
    if isinstance(ans, dict):
        data = ans.get("retrieved_data")
        if isinstance(data, list) and data:
            return ", ".join(str(x) for x in data)
        return str(ans.get("status") or "")
    return "" if ans is None else str(ans)


# ---------------------------------------------------------------- one rollout

async def llm_call(msgs, task_dir):
    t = {"t_llm_send": now()}
    kw = dict(model=a.model, messages=msgs, temperature=a.temperature, top_p=0.9, max_tokens=a.max_tokens,
              extra_headers={"x-task": str(task_dir)})
    if not a.stream:
        r = await LLM.chat.completions.create(**kw)
        t["t_first_token"] = t["t_llm_done"] = now()
        return r.choices[0].message.content or "", r.usage.prompt_tokens, r.usage.completion_tokens, t
    text, usage = [], None
    stream = await LLM.chat.completions.create(**kw, stream=True, stream_options={"include_usage": True})
    async for ch in stream:
        if ch.choices and ch.choices[0].delta.content:
            if "t_first_token" not in t:
                t["t_first_token"] = now()
            text.append(ch.choices[0].delta.content)
        if ch.usage:
            usage = ch.usage
    t["t_llm_done"] = now()
    t.setdefault("t_first_token", t["t_llm_done"])
    return "".join(text), getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None), t


async def rollout(pw, task, k, name, ip, tm, wave_start):
    d = OUT / f"{task['task_id']}__g{k}"
    d.mkdir(parents=True, exist_ok=True)
    res = {"task_id": task["task_id"], "k": k, "container": name, "setup": tm, "t_wave_start": wave_start}
    br = None
    try:
        br, ctx = await open_browser(pw, ip, task, tm)
        res["t_rollout_start"] = now()
        hist, cur, answer, steps = [], 0, None, 0
        for n in range(1, a.max_steps + 1):
            s = {"step": n, "t_obs_start": now()}
            page = ctx.pages[cur]
            s["url_before"] = page.url
            rows, tabs = await read_page(page, ctx)
            text, _ = linearize(rows)
            hs = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(hist[-HISTORY:])) or "(none)"
            tabs_s = "\n".join(f"[{i}]{' (current)' if i == cur else ''} {t}" for i, t in enumerate(tabs))
            msgs = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": f"Task: {task['intent']}\n\nOpen tabs:\n{tabs_s}\n\nCurrent URL: {page.url}\n\n"
                                                f"Previous actions:\n{hs}\n\nPage elements:\n{text}\n\nNext action?"}]
            s["t_obs_end"], s["rows"] = now(), len(rows)
            resp, s["prompt_tokens"], s["completion_tokens"], lt = await llm_call(msgs, d)
            s.update(lt)
            try:
                act = parse(resp)
            except Exception as e:
                act = {"action": "invalid", "error": repr(e)[:200]}
            i = act.get("id")
            hist.append(json.dumps(act) + (f'  [{rows[i][0]} "{rows[i][1][:60]}"]' if isinstance(i, int) and 0 <= i < len(rows) else ""))
            s["action"] = act
            jl(d / "chat.jsonl", {"step": n, "messages": msgs, "response": resp, "action": act, "rows": rows, "url": page.url,
                                  "t": {"llm_start": lt["t_llm_send"], "llm_end": lt["t_llm_done"]}})
            steps = n
            if act.get("action") == "done":
                answer = act
                s["t_act_start"] = s["t_act_end"] = s["t_settle_end"] = now()
                jl(d / "steps.jsonl", s)
                break
            s["t_act_start"] = now()
            try:
                cur = await execute(ctx, cur, act)
            except Exception as e:
                s["error"] = repr(e)[:300]
            s["t_act_end"] = now()
            try:
                await ctx.pages[cur].wait_for_load_state("domcontentloaded", timeout=10_000)
            except Exception:
                pass
            await asyncio.sleep(a.sleep_after_action)
            s["t_settle_end"], s["url_after"] = now(), ctx.pages[cur].url
            jl(d / "steps.jsonl", s)
        res.update(t_rollout_end=now(), steps=steps, answer=answer, stop="done" if answer else "max_steps")
        res["t_eval_start"] = now()
        try:
            res["reward"] = await lite_eval.evaluate(task, lite_answer(answer or {}), ctx.pages[cur])
        except Exception as e:
            res["reward"], res["eval_error"] = None, repr(e)[:300]   # unscored, never a silent 0
        res["t_eval_end"] = now()
    except Exception as e:
        res["error"] = repr(e)[:500]
    finally:
        if br:
            try:
                await br.close()
            except Exception:
                pass
    (d / "result.json").write_text(json.dumps(res, indent=1, default=str))
    event("rollout_done", task=task["task_id"], k=k, reward=res.get("reward"), steps=res.get("steps"), error=res.get("error"),
          secs=round(res.get("t_rollout_end", now()) - res.get("t_rollout_start", now()), 1))
    return res


# ---------------------------------------------------------------- waves

async def wave(pw, wi, group_tasks):
    names = [(t, k, f"wa-{RUN}-w{wi}-t{t['task_id']}-g{k}") for t in group_tasks
             for k in (ONLY.get(t["task_id"]) or range(a.rollouts))]
    event("wave_setup_start", wave=wi, tasks=[t["task_id"] for t in group_tasks], envs=len(names))
    setups = await asyncio.gather(*(setup_env(n, t, f"w{wi}-t{t['task_id']}") for t, k, n in names), return_exceptions=True)
    event("wave_setup_done", wave=wi, failed=sum(isinstance(s, Exception) for s in setups),
          errors=[repr(s)[:200] for s in setups if isinstance(s, Exception)][:3])
    wave_start = now()   # all rollouts of the batch start together
    try:
        await asyncio.gather(*(rollout(pw, t, k, n, *s, wave_start) for (t, k, n), s in zip(names, setups)
                               if not isinstance(s, Exception)), return_exceptions=True)
    finally:
        event("wave_rollouts_done", wave=wi)
        for _, _, n in names:
            LIVE.pop(n, None)
    # teardown = kill only (0.26 s each; frees CPU and memory). Removal is left for after the run
    # (setup/cleanup_recording.sh): podman's btrfs driver walks the whole ~200k-file rootfs before deleting a container's
    # snapshot (~8 s each, one at a time under podman's storage lock), which stalled the next wave's setup.
    await pod("kill", "-s", "KILL", *[n for _, _, n in names], check=False)
    event("wave_teardown_done", wave=wi, envs=len(names), removed=False)
    KILLED.extend(n for _, _, n in names)


async def main():
    ids = sorted(ONLY) if ONLY else [int(x) for x in a.tasks.split(",")]
    if ONLY:
        a.groups_at_once = len(ids)   # every re-recorded rollout in one wave
    (OUT / "config.json").write_text(json.dumps({**vars(a), "task_ids": ids}, indent=1))
    event("run_start", tasks=len(ids), rollouts=a.rollouts, batch=a.groups_at_once * a.rollouts, llm=a.llm_url)
    bg = [asyncio.create_task(f()) for f in (sample_memory, sample_vllm, sample_rtt)]
    waves = [ids[i:i + a.groups_at_once] for i in range(0, len(ids), a.groups_at_once)]
    if a.limit_waves:
        waves = waves[:a.limit_waves]
    async with async_playwright() as pw:
        for wi, w in enumerate(waves):
            await wave(pw, wi, [TASKS[t] for t in w])
    (OUT / "killed_containers.txt").write_text("\n".join(KILLED) + "\n")   # to remove after the run
    for b in bg:
        b.cancel()
    event("run_done")
    if os.environ.get("SUDO_UID"):
        subprocess.run(["chown", "-R", f"{os.environ['SUDO_UID']}:{os.environ['SUDO_GID']}", str(OUT)])


if __name__ == "__main__":
    import signal
    signal.signal(signal.SIGHUP, signal.SIG_IGN)   # a closed launching shell must not kill the run
    asyncio.run(main())
