"""抓取個股近期新聞，並用 Claude Haiku 過濾出真正的催化劑。"""
from __future__ import annotations

import asyncio
import json

import httpx
from anthropic import AsyncAnthropic
from selectolax.parser import HTMLParser
from tenacity import retry, stop_after_attempt, wait_exponential

from ..utils.config import Settings
from ..utils.logger import logger
from .models import Catalyst

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9"}
MAX_HEADLINES_PER_STOCK = 10
MAX_CATALYSTS_RETURN = 3


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=4))
async def _fetch_yahoo_news(client: httpx.AsyncClient, ticker: str) -> list[Catalyst]:
    url = f"https://tw.stock.yahoo.com/quote/{ticker}.TW/news"
    resp = await client.get(url, headers=HEADERS, timeout=15.0)
    resp.raise_for_status()
    tree = HTMLParser(resp.text)

    items: list[Catalyst] = []
    for a in tree.css("a[href*='/news/']"):
        title = a.text(strip=True)
        href = a.attributes.get("href", "")
        if not title or len(title) < 8:
            continue
        full_url = href if href.startswith("http") else f"https://tw.stock.yahoo.com{href}"
        items.append(Catalyst(title=title, url=full_url))
        if len(items) >= MAX_HEADLINES_PER_STOCK:
            break
    return items


async def _fetch_headlines(ticker: str) -> list[Catalyst]:
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            return await _fetch_yahoo_news(client, ticker)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Yahoo 新聞抓取失敗 {ticker}: {exc}")
            return []


# ---------- LLM 過濾 ----------

_FILTER_PROMPT = """你是台股研究員。以下是 {name}({ticker}) 近期的新聞標題清單，請從中挑出最多 3 條\
真正可能影響股價的「催化劑」（重大訂單、財報、法說會、產業重大事件、政策、合併、CEO 變動等），\
忽略例行性更新與雜訊。

新聞標題：
{titles}

請以 JSON 陣列回覆，格式：
[{{"title": "...", "summary": "一句話描述為何重要"}}]

若都不重要，回傳 []
只輸出 JSON，不要任何其他文字。
"""


async def _filter_with_haiku(
    client: AsyncAnthropic,
    model: str,
    ticker: str,
    name: str,
    headlines: list[Catalyst],
) -> list[Catalyst]:
    if not headlines:
        return []
    titles_block = "\n".join(f"- {c.title}" for c in headlines[:MAX_HEADLINES_PER_STOCK])
    prompt = _FILTER_PROMPT.format(name=name, ticker=ticker, titles=titles_block)
    msg = await client.messages.create(
        model=model,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    text = msg.content[0].text.strip() if msg.content else "[]"
    text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        items = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Haiku 回覆非合法 JSON ({ticker})：{text[:120]}")
        return []

    # 將標題對回 URL
    title_to_url = {c.title: c.url for c in headlines}
    out: list[Catalyst] = []
    for it in items[:MAX_CATALYSTS_RETURN]:
        if not isinstance(it, dict):
            continue
        title = it.get("title", "").strip()
        summary = it.get("summary", "").strip()
        if not title:
            continue
        out.append(Catalyst(title=title, summary=summary, url=title_to_url.get(title)))
    return out


# ---------- 主入口 ----------

async def fetch_catalysts_for(
    ticker: str,
    name: str,
    *,
    settings: Settings | None = None,
) -> list[Catalyst]:
    """回傳該股 1-3 條重要催化劑。"""
    settings = settings or Settings.load()
    headlines = await _fetch_headlines(ticker)
    if not headlines:
        return []
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return await _filter_with_haiku(
        client, settings.claude_filter_model, ticker, name, headlines
    )


async def fetch_catalysts_batch(
    stocks: list[tuple[str, str]],
    *,
    settings: Settings | None = None,
    concurrency: int = 4,
) -> dict[str, list[Catalyst]]:
    settings = settings or Settings.load()
    sem = asyncio.Semaphore(concurrency)

    async def _one(ticker: str, name: str) -> tuple[str, list[Catalyst]]:
        async with sem:
            try:
                return ticker, await fetch_catalysts_for(ticker, name, settings=settings)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"催化劑抓取失敗 {ticker}: {exc}")
                return ticker, []

    results = await asyncio.gather(*(_one(t, n) for t, n in stocks))
    return dict(results)
