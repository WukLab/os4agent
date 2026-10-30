"""Step 1b checks of lite_eval.py (the WebArena-Lite shopping evaluator port).
  /mnt/data/ssd1/yutong_data/venv-pw1.44.0/bin/python test_lite_eval.py [equiv] [recorded] [live]   (default: all)
equiv     the original VAB-WebArena-Lite evaluators.py (heavy imports stubbed) and the port give the same score for
          every recorded final answer / final URL against every Lite shopping task's references.
recorded  string_match / url_match scores of the step-133 Lite rollouts (poc-trajectories data, original image).
live      on a fresh wa-shop-orig-browser container (docker): every program_html task scores 0 (fuzzy ones: None,
          no judge); then four goals done by hand through the in-container browser score 1: wishlist (120),
          newsletter (121), cart (103), address (129); and the REST helper finds the latest order.
"""
import asyncio, importlib.util, json, sys, types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import lite_eval as L  # noqa: E402

LITE_SRC = Path("/mnt/data/ssd1/yutong_data/webarena_src/VisualAgentBench/VAB-WebArena-Lite/new/evaluators.py")
RECORDED = Path.home() / "Repos/mlsys-resubmission/poc-trajectories/data/webarena/wa_lite_orig_shopping"
TASKS = L.load_tasks()
fails = []


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)
    if not ok:
        fails.append(name)


def recorded_rollouts():
    """(task_id, final answer, final URL with the old host replaced by localhost) per finished rollout."""
    out = []
    for d in sorted(RECORDED.iterdir()):
        if not (d / "rollout.json").exists():
            continue
        r = json.load(open(d / "rollout.json"))
        ans = r.get("answer") or {}
        steps = [json.loads(l) for l in open(d / "steps.jsonl") if l.strip()]
        urls = [s["url"] for s in steps if s.get("url")]
        url = (urls[-1] if urls else "").replace("http://wa-shopping-orig-0", "http://localhost")
        out.append((int(r["task_id"]), str(ans.get("answer", "")) if isinstance(ans, dict) else str(ans), url))
    return out


def original_module():
    """Import Lite's evaluators.py with its dependencies stubbed (they are not needed for string / URL scoring)."""
    stub = lambda name, **attrs: sys.modules.setdefault(name, types.ModuleType(name)).__dict__.update(attrs)
    stub("evaluate"); stub("PIL", Image=None); stub("PIL.Image")
    stub("beartype", beartype=lambda f: f); stub("beartype.door", is_bearable=lambda *a: True)
    stub("browser_env"); stub("browser_env.actions", Action=dict); stub("browser_env.utils", StateInfo=dict)
    stub("evaluation_harness", image_utils=None); stub("evaluation_harness.image_utils")
    stub("evaluation_harness.helper_functions", PseudoPage=object,
         **{n: None for n in ("gitlab_get_project_memeber_role", "llm_fuzzy_match", "llm_ua_match",
                              "reddit_get_latest_comment_content_by_username", "reddit_get_latest_comment_obj_by_username",
                              "reddit_get_parent_comment_username_of_latest_comment_by_username",
                              "shopping_get_latest_order_url", "shopping_get_num_reviews", "shopping_get_order_product_name_list",
                              "shopping_get_order_product_option", "shopping_get_order_product_quantity",
                              "shopping_get_product_attributes", "shopping_get_product_price", "shopping_get_rating_as_percentage",
                              "shopping_get_sku_latest_review_author", "shopping_get_sku_latest_review_rating",
                              "shopping_get_sku_latest_review_text", "shopping_get_sku_latest_review_title", "get_query_text",
                              "get_query_text_lowercase", "reddit_get_post_url")})
    spec = importlib.util.spec_from_file_location("lite_original_evaluators", LITE_SRC)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def equiv():
    O = original_module()
    rolls = recorded_rollouts()
    n = bad = 0
    for tid, task in TASKS.items():
        ev = task["eval"]
        for _, answer, url in rolls:
            if "string_match" in ev["eval_types"] and "fuzzy_match" not in ev["reference_answers"]:
                pred = O.StringEvaluator.clean_answer(answer)
                orig = 1.0
                for approach, value in ev["reference_answers"].items():
                    if approach == "exact_match":
                        orig *= O.StringEvaluator.exact_match(ref=value, pred=pred)
                    else:
                        for mv in value:
                            orig *= any(O.StringEvaluator.must_include(ref=v, pred=pred) for v in mv.split(" |OR| "))
                ours = asyncio.run(L.string_match(task, answer, None))
                n += 1; bad += float(orig) != ours
            if "url_match" in ev["eval_types"]:
                cfg = Path("/tmp") / f"lite_cfg_{tid}.json"
                cfg.write_text(json.dumps({**task, "eval": {**ev, "reference_url": ev["reference_url"].replace("__SHOPPING__", L.SHOPPING)}}))
                orig = O.URLExactEvaluator()([], cfg, types.SimpleNamespace(url=url))
                n += 1; bad += float(orig) != L.url_match(task, url)
    check("port = original on string/url scoring", n > 1000 and bad == 0, f"{n} comparisons, {bad} differ")


def recorded():
    rolls = recorded_rollouts()
    by = {"1.0": 0, "0.0": 0, "skipped (fuzzy or program_html)": 0}
    for tid, answer, url in rolls:
        t = TASKS[tid]
        if "program_html" in t["eval"]["eval_types"] or "fuzzy_match" in (t["eval"].get("reference_answers") or {}):
            by["skipped (fuzzy or program_html)"] += 1
            continue
        s = 1.0
        if "string_match" in t["eval"]["eval_types"]:
            s *= asyncio.run(L.string_match(t, answer, None))
        if "url_match" in t["eval"]["eval_types"]:
            s *= L.url_match(t, url)
        by[str(s)] += 1
    check("recorded rollouts scored", sum(by.values()) == len(rolls), json.dumps(by))


async def live():
    import subprocess
    from playwright.async_api import async_playwright
    name, cdp = "wa-eval-test", 9291
    sh = lambda *c, check=True: subprocess.run(c, capture_output=True, text=True, check=check).stdout.strip()
    mysql = ["mysql", "-u", "magentouser", "-pMyPassword", "magentodb", "-e"]
    sh("docker", "rm", "-f", name, check=False)
    sh("docker", "run", "-d", "--name", name, "--shm-size=2g", "-p", f"127.0.0.1:{cdp}:9222", "wa-shop-orig-browser:latest")
    try:
        for _ in range(300):
            if subprocess.run(["docker", "exec", name, *mysql, "select 1"], capture_output=True).returncode == 0:
                break
            await asyncio.sleep(2)
        sh("docker", "exec", name, "/var/www/magento2/bin/magento", "setup:store-config:set", "--base-url=http://localhost/")
        sh("docker", "exec", name, *mysql, "UPDATE core_config_data SET value='http://localhost/' WHERE path = 'web/secure/base_url';")
        sh("docker", "exec", name, "/var/www/magento2/bin/magento", "cache:flush")
        sh("docker", "exec", name, "curl", "-s", "-o", "/dev/null", "--max-time", "300", "http://localhost/")
        async with async_playwright() as pw:
            for _ in range(60):
                try:
                    br = await pw.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp}"); break
                except Exception:
                    await asyncio.sleep(2)
            page = br.contexts[0].pages[0]
            await page.goto("http://localhost/customer/account/login/", timeout=120_000)
            await page.fill("#email", "emma.lopez@gmail.com"); await page.fill("#pass", "Password.123")
            await page.click("#send2", timeout=60_000); await page.wait_for_load_state("load")
            url = await L.shopping_get_latest_order_url(page)
            check("REST helper: latest order url", "/sales/order/view/order_id/" in url, url)
            for tid in (29, 103, 104, 109, 117, 118, 119, 120, 121, 123, 129, 142):
                t = TASKS[tid]
                await page.goto(t["start_url"].replace("__SHOPPING__", L.SHOPPING), timeout=120_000)
                s = await L.evaluate(t, "", page)
                fuzzy = any("fuzzy_match" in p["required_contents"] for p in t["eval"]["program_html"])
                check(f"fresh site, task {tid} scores {'None' if fuzzy else '0'}", s is None if fuzzy else s == 0.0, str(s))

            async def done_by_hand(tid, steps):
                t = TASKS[tid]
                await page.goto(t["start_url"].replace("__SHOPPING__", L.SHOPPING), timeout=120_000)
                await page.wait_for_load_state("networkidle")
                await steps()
                s = await L.evaluate(t, "", page)
                check(f"goal done by hand, task {tid} scores 1", s == 1.0, f"{s}  ({t['intent'][:60]})")

            async def wishlist_this():
                await page.click("a.action.towishlist", timeout=60_000); await page.wait_for_load_state("load")

            async def newsletter():
                await page.goto("http://localhost/newsletter/manage/"); await page.check('[title="General Subscription"]')
                await page.click("button.action.save", timeout=60_000); await page.wait_for_load_state("load")

            async def cart_candles():
                await page.goto("http://localhost/catalogsearch/result/?q=SPAAS+White+Taper+Candles")
                await page.locator(".product-item-link").first.click(); await page.wait_for_load_state("networkidle")
                await page.click("#product-addtocart-button", timeout=60_000); await asyncio.sleep(5)

            async def address():
                await page.goto("http://localhost/customer/address/"); await page.wait_for_load_state("networkidle")
                await page.locator(".box-address-billing a.action.edit, .box-address-shipping a.action.edit").first.click()
                await page.wait_for_load_state("networkidle")
                await page.fill("#street_1", "111 Magnolia Path"); await page.fill("#city", "Atlanta")
                await page.select_option("#region_id", label="Georgia"); await page.fill("#zip", "30303")
                await page.click("button.action.save.primary", timeout=60_000); await page.wait_for_load_state("load")

            await done_by_hand(120, wishlist_this)
            await done_by_hand(121, newsletter)
            await done_by_hand(103, cart_candles)
            await done_by_hand(129, address)
            await br.close()
    finally:
        sh("docker", "rm", "-f", name, check=False)


if __name__ == "__main__":
    parts = sys.argv[1:] or ["equiv", "recorded", "live"]
    if "equiv" in parts:
        equiv()
    if "recorded" in parts:
        recorded()
    if "live" in parts:
        asyncio.run(live())
    print("ALL PASSED" if not fails else f"FAILED: {fails}")
    sys.exit(1 if fails else 0)
