"""Add --screen-cache to wa_replay.py (run in its directory)."""
s = open("wa_replay.py").read()


def rep(old, new, cnt=1):
    global s
    assert s.count(old) == cnt, (s.count(old), old[:70])
    s = s.replace(old, new)


rep('''ap.add_argument("--image", default="localhost/wa-shop-browser142:latest")''',
'''ap.add_argument("--image", default="localhost/wa-shop-browser142:latest")
ap.add_argument("--screen-cache", type=int, default=0,
                help="1: (task, page rows, action) seen before -> the next page rows are served at once and the model time "
                     "starts; the copy runs the action, settles and reads the page in the background, and that real page "
                     "is checked against the served one before the next action (mismatch: the model time is redone)")
ap.add_argument("--screen-warm", default="", help="comma-separated earlier trace dirs (chat.jsonl) the screen cache learns first")''')

rep('''# ---------------------------------------------------------------- one replayed rollout
''', '''# ---------------------------------------------------------------- screen cache (--screen-cache)

import hashlib  # noqa: E402
SC = {}  # (task, rows hash, action key) -> next page rows


def sc_key(task, rows, act):
    kind = act.get("action")
    if kind == "done":
        return None
    i = act.get("id")
    tgt = "|".join(map(str, rows[i][:2])) if isinstance(i, int) and 0 <= i < len(rows) else ""
    arg = act.get("text") or act.get("option") or act.get("url") or act.get("direction") or "+".join(map(str, act.get("keys", []))) or ""
    return task, hashlib.sha1(json.dumps(rows).encode()).hexdigest(), f"{kind} {tgt} {arg}"


def sc_warm(dirs):
    n = 0
    for root in dirs:
        for d in Path(root).glob("*__g*"):
            f = d / "chat.jsonl"
            if not f.exists():
                continue
            ch = [json.loads(l) for l in open(f) if l.strip()]
            t = int(d.name.split("__g")[0])
            for i in range(len(ch) - 1):
                k = sc_key(t, ch[i]["rows"], ch[i]["action"])
                if k:
                    SC.setdefault(k, ch[i + 1]["rows"])
                    n += 1
    return n


async def sc_background(ctx, cur, act, key):
    """A served step on the real copy: the action, the settle, the next page read. -> (tab, real rows, error)"""
    err = None
    try:
        cur = await asyncio.wait_for(execute(ctx, cur, act), a.step_timeout)
    except Exception as e:
        err = repr(e)[:300]
    try:
        await ctx.pages[cur].wait_for_load_state("domcontentloaded", timeout=10_000)
    except Exception:
        pass
    await asyncio.sleep(a.sleep_after_action)
    rows, _ = await asyncio.wait_for(read_page(ctx.pages[cur], ctx), a.step_timeout)
    rows = json.loads(json.dumps(rows))
    if key:
        SC[key] = rows
    return cur, rows, err


# ---------------------------------------------------------------- one replayed rollout
''')

rep('''        cur, answer = 0, None
        for c, rs in zip(chat, rsteps):
            act = c["action"]
            s = {"step": c["step"], "t_obs_start": now(), "action": act}
            page = ctx.pages[cur]
            s["url_before"], s["url_rec"] = page.url, c["url"]
            # step timeouts: a hung browser (CRIU run, 120__g1: CDP stopped answering) fails the rollout, not the run
            rows, _ = await asyncio.wait_for(read_page(page, ctx), a.step_timeout)
            s["t_obs_end"] = now()''', '''        cur, answer = 0, None
        pending = served = prev_key = None  # --screen-cache: the background step, the page served, the last real step's key
        sc = {"hit": 0, "miss": 0, "reject": 0, "waited_s": 0.0}
        for c, rs in zip(chat, rsteps):
            act = c["action"]
            s = {"step": c["step"], "t_obs_start": now(), "action": act}
            page = ctx.pages[cur]
            s["url_before"], s["url_rec"] = page.url, c["url"]
            if served is not None:  # the previous step was served from the cache: this is its page, no read
                rows, s["sc_served"] = served, True
            else:
                # step timeouts: a hung browser (CRIU run, 120__g1: CDP stopped answering) fails the rollout, not the run
                rows, _ = await asyncio.wait_for(read_page(page, ctx), a.step_timeout)
                rows = json.loads(json.dumps(rows))
                if a.screen_cache and prev_key:
                    SC[prev_key] = rows
            s["t_obs_end"] = now()''')

rep('''            s["t_llm_send"] = now()
            await asyncio.sleep(a.replay_latency * s["llm_rec_s"])
            s["t_llm_done"] = now()''', '''            s["t_llm_send"] = now()
            await asyncio.sleep(a.replay_latency * s["llm_rec_s"])
            s["t_llm_done"] = now()
            if pending is not None:  # the served step's real run: check its page before acting on it
                t_w = now()
                cur, real, err = await pending
                pending = None
                s["sc_waited_s"] = round(now() - t_w, 3)
                sc["waited_s"] += s["sc_waited_s"]
                if err:
                    s["sc_bg_error"] = err
                if real != served:  # the cached page was wrong: think again on the real one
                    sc["reject"] += 1
                    s["sc_rejected"] = True
                    rows = real
                    await asyncio.sleep(a.replay_latency * s["llm_rec_s"])
                    s["t_llm_done"] = now()
                served = None''')

rep('''            s["t_act_start"] = now()
            try:
                cur = await asyncio.wait_for(execute(ctx, cur, act), a.step_timeout)''', '''            key = sc_key(task["task_id"], rows, act) if a.screen_cache else None
            if key and key in SC:  # seen before: serve the next page now, run the action in the background
                sc["hit"] += 1
                served = SC[key]
                pending = asyncio.create_task(sc_background(ctx, cur, act, key))
                s["sc"] = "hit"
                s["t_act_start"] = s["t_act_end"] = s["t_settle_end"] = now()
                jl(d / "steps.jsonl", s)
                prev_key = None
                continue
            if a.screen_cache:
                sc["miss"] += 1
                prev_key = key
            s["t_act_start"] = now()
            try:
                cur = await asyncio.wait_for(execute(ctx, cur, act), a.step_timeout)''')

rep('''        res.update(t_rollout_end=now(), steps=len(chat), answer=answer)''', '''        if pending is not None:  # ended on a served step: the copy finishes it before scoring
            cur, _, _ = await pending
            pending = None
        res.update(t_rollout_end=now(), steps=len(chat), answer=answer)
        if a.screen_cache:
            res["screen_cache"] = sc''')
open("wa_replay.py", "w").write(s)
print("patched")
