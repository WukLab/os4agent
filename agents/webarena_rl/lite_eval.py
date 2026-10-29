"""WebArena-Lite scoring for the shopping tasks, ported from VAB-WebArena-Lite (THUDM VisualAgentBench @9055fc2,
`VAB-WebArena-Lite/new/evaluators.py` and `helper_functions_eval.py`) without the visualwebarena package.

Only what the 45 Lite shopping tasks use (tasks/lite_shopping.json): string_match (exact_match, must_include,
fuzzy_match), url_match (all "GOLD in PRED") and program_html (exact_match, must_include, fuzzy_match on a page or a JS
locator; one helper, shopping_get_latest_order_url). The logic, the clean-ups and the 3 s sleep after a navigation are
the original's. Differences, all forced by the setting:
- The page is our Playwright (async) page inside the environment, so `__SHOPPING__` is http://localhost.
- shopping_get_latest_order_url calls Magento's REST API with fetch() from that page (inside the container), not
  requests from the evaluating host.
- fuzzy_match's judge was GPT-4-1106-preview; here it is any OpenAI-compatible endpoint (`judge=`), same prompt,
  temperature 0, same verdict parsing. With no judge, fuzzy_match tasks score None (unscored).
"""
import asyncio, json
from urllib.parse import urljoin

from nltk.tokenize import word_tokenize

SHOPPING = "http://localhost"
ADMIN = ("admin", "admin1234")   # WebArena's ACCOUNTS["shopping_site_admin"]


class Unscored(Exception):
    """A fuzzy_match check with no judge configured."""


# ---------------------------------------------------------------- string checks (StringEvaluator)

def clean_answer(answer):
    answer = str(answer)
    if answer.startswith("'") and answer.endswith("'"):
        answer = answer[1:-1]
    elif answer.startswith('"') and answer.endswith('"'):
        answer = answer[1:-1]
    return answer.lower()


def exact_match(ref, pred):
    return float(clean_answer(pred) == clean_answer(ref))


def must_include(ref, pred):
    clean_ref, clean_pred = clean_answer(ref), clean_answer(pred)
    if len(word_tokenize(clean_ref)) == 1:   # a single-word reference must be a whole token (avoids "0" in "10")
        tok_pred = word_tokenize(clean_pred)
        for token in list(tok_pred):
            if "/" in token:
                tok_pred.extend(token.split("/"))
        return float(clean_ref in tok_pred)
    return float(clean_ref in clean_pred)


FUZZY_PROMPT = ("Help a teacher to grade the answer of a student given a question. Keep in mind that the student may "
                "use different phrasing or wording to answer the question. The goal is to evaluate whether the answer "
                "is semantically equivalent to the reference answer.\n"
                "question: {question}\nreference answer: {reference}\n"
                "all the string 'N/A' that you see is a special sequence that means 'not achievable'\n"
                "student answer: {pred}\n"
                "Conclude the judgement by 'correct', 'incorrect', or 'partially correct'. Only output one of these "
                "options, and nothing else.")


async def fuzzy_match(ref, pred, intent, judge):
    """llm_fuzzy_match. judge: (AsyncOpenAI client, model name) or None."""
    if judge is None:
        raise Unscored("fuzzy_match needs a judge")
    client, model = judge
    r = await client.chat.completions.create(model=model, temperature=0, max_tokens=768, top_p=1.0, messages=[
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": FUZZY_PROMPT.format(question=intent, reference=ref, pred=pred)}])
    response = (r.choices[0].message.content or "").lower()
    if "partially correct" in response or "incorrect" in response:
        return 0.0
    if "correct" not in response:
        raise ValueError(f"judge gave no verdict: {response[:200]!r}")
    return 1.0


async def string_match(task, answer, judge):
    pred, score = clean_answer(answer), 1.0
    for approach, value in task["eval"]["reference_answers"].items():
        if approach == "exact_match":
            score *= exact_match(value, pred)
        elif approach == "must_include":
            for must_value in value:
                score *= any(must_include(v, pred) for v in must_value.split(" |OR| "))
        elif approach == "fuzzy_match":
            if value == "N/A":   # not used by the shopping tasks (it needs ua_match)
                raise NotImplementedError("fuzzy_match N/A")
            score *= await fuzzy_match(", ".join(value), pred, task["intent"], judge)
        else:
            raise NotImplementedError(approach)
    return score


# ---------------------------------------------------------------- URL check (URLExactEvaluator)

def clean_url(url):
    url = str(url).replace("localhost", "127.0.0.1")
    return url[:-1] if url.endswith("/") else url


def url_match(task, page_url):
    pred = clean_url(page_url)
    refs = [clean_url(u.replace("__SHOPPING__", SHOPPING)) for u in task["eval"]["reference_url"].split(" |OR| ")]
    rule = task["eval"].get("url_note", "EXACT")
    if rule == "EXACT":
        return float(pred in refs)
    if rule == "GOLD in PRED":
        return float(any(ref in pred for ref in refs))
    raise ValueError(rule)


# ---------------------------------------------------------------- page-content check (HTMLContentExactEvaluator)

LATEST_ORDER_JS = """async ([user, pw]) => {
  const t = await (await fetch('/rest/default/V1/integration/admin/token', {method: 'POST',
      headers: {'content-type': 'application/json'}, body: JSON.stringify({username: user, password: pw})})).json();
  const q = 'searchCriteria[sortOrders][0][field]=created_at&searchCriteria[sortOrders][0][direction]=DESC'
          + '&searchCriteria[pageSize]=1';
  const r = await fetch('/rest/V1/orders?' + q, {headers: {'Authorization': 'Bearer ' + t, 'Content-Type': 'application/json'}});
  if (r.status !== 200) throw new Error('orders: http ' + r.status);
  return (await r.json()).items[0].increment_id;
}"""


async def shopping_get_latest_order_url(page):
    order_id = int(await page.evaluate(LATEST_ORDER_JS, list(ADMIN)))
    return f"{SHOPPING}/sales/order/view/order_id/{order_id}/"


async def program_html(task, page, judge):
    score = 1.0
    for target in task["eval"]["program_html"]:
        target_url = target["url"]
        if target_url.startswith("func:"):
            func = target_url.split("func:")[1]
            if func != "shopping_get_latest_order_url()":
                raise NotImplementedError(func)
            target_url = await shopping_get_latest_order_url(page)
        else:
            target_url = target_url.replace("__SHOPPING__", SHOPPING)
        locator = target["locator"]
        if target_url != "last":
            await page.goto(target_url)
            await asyncio.sleep(3)   # the original's hard-coded sleep
        if not locator.strip():
            selected = await page.content()
        elif locator.startswith("document.") or locator.startswith("[...document."):
            for prep in target.get("prep_actions", []):
                try:
                    await page.evaluate(f"() => {prep}")
                except Exception:
                    pass
            try:
                selected = str(await page.evaluate(f"() => {locator}")) or ""
            except Exception:   # the page is wrong
                selected = ""
        else:
            raise NotImplementedError(locator)
        req = target["required_contents"]
        if "exact_match" in req:
            score *= exact_match(req["exact_match"], selected)
        elif "must_include" in req:
            for content in req["must_include"]:
                score *= any(must_include(c, selected) for c in content.split(" |OR| "))
        elif "fuzzy_match" in req:
            score *= await fuzzy_match(", ".join(req["fuzzy_match"]), selected, task["intent"], judge)
        else:
            raise NotImplementedError(list(req))
    return score


# ---------------------------------------------------------------- router (evaluator_router + EvaluatorComb)

async def evaluate(task, answer, page, judge=None):
    """Score one finished rollout: answer = the agent's final answer text, page = its final page (live). Returns
    1.0 / 0.0, or None when a fuzzy_match check has no judge. Like the original, the evaluators run in order and the
    scores multiply."""
    score = 1.0
    try:
        for kind in task["eval"]["eval_types"]:
            if kind == "string_match":
                score *= await string_match(task, answer, judge)
            elif kind == "url_match":
                score *= url_match(task, page.url)
            elif kind == "program_html":
                score *= await program_html(task, page, judge)
            else:
                raise NotImplementedError(kind)
    except Unscored:
        return None
    return float(score)


def load_tasks(path=None):
    from pathlib import Path
    return {t["task_id"]: t for t in json.load(open(path or Path(__file__).with_name("tasks") / "lite_shopping.json"))}
