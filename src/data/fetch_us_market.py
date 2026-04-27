"""抓昨夜美股的指數與 AI 供應鏈關鍵股漲跌，給講稿 market 段當引子。

來源：Yahoo Finance v8 chart endpoint（無需 API key、JSON 結構穩定）。
為了與既有風格一致，使用 httpx + tenacity，不引入 yfinance/pandas 依賴。

整支 fetcher 失敗時 graceful return None，由 main pipeline 略過 — 美股不是
00981A 節目的主軸，缺漏不應阻斷產製流程。
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..utils.logger import logger
from .models import USMarketSnapshot, USTickerQuote

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)

NY = ZoneInfo("America/New_York")

# (symbol, 中文/顯示名稱, 類別)
# 指數：給「美股大盤情緒」一個錨點
# 個股：選 00981A AI 供應鏈直接相關的權值名 — 反映需求/競爭/同業壓力
SYMBOLS: list[tuple[str, str, str]] = [
    ("^GSPC", "S&P 500", "index"),
    ("^IXIC", "Nasdaq", "index"),
    ("^SOX", "費城半導體指數", "index"),
    ("NVDA", "輝達（NVIDIA）", "stock"),
    ("AMD", "超微（AMD）", "stock"),
    ("AVGO", "博通（Broadcom）", "stock"),
    ("TSM", "台積電 ADR", "stock"),
]


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=6))
async def _fetch_one(client: httpx.AsyncClient, symbol: str) -> dict:
    """抓單一 ticker 最近一個交易日的 meta（含 close 與前日 close）。"""
    url = f"https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
    params = {"interval": "1d", "range": "5d"}
    r = await client.get(url, params=params, timeout=15.0)
    r.raise_for_status()
    j = r.json()
    err = j.get("chart", {}).get("error")
    if err:
        raise RuntimeError(f"Yahoo Finance 回傳錯誤 {symbol}: {err}")
    results = j.get("chart", {}).get("result") or []
    if not results:
        raise RuntimeError(f"Yahoo Finance 無 {symbol} 結果")
    return results[0].get("meta") or {}


def _to_quote(symbol: str, display: str, category: str, meta: dict) -> USTickerQuote | None:
    """把 Yahoo meta 轉成 USTickerQuote；缺欄位則回 None 略過。"""
    close = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    if close is None or prev is None or prev == 0:
        return None
    change = close - prev
    change_pct = change / prev * 100
    return USTickerQuote(
        symbol=symbol,
        display_name=display,
        category=category,
        close=float(close),
        prev_close=float(prev),
        change=float(change),
        change_pct=float(change_pct),
    )


def _session_date_from_meta(meta: dict) -> date | None:
    """用 regularMarketTime（unix 秒）換算紐約日期，作為節目開場引用的『昨夜』日期。"""
    ts = meta.get("regularMarketTime")
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).astimezone(NY).date()


async def fetch_us_market_overnight() -> USMarketSnapshot | None:
    """並行抓取所有 symbols 的昨夜表現；任何 ticker 個別失敗會略過該檔。

    全部失敗則回傳 None，由 main pipeline 判斷是否缺資料仍要走完。
    """
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
        tasks = [_fetch_one(client, sym) for sym, _, _ in SYMBOLS]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    quotes: list[USTickerQuote] = []
    session_date: date | None = None
    for (sym, display, cat), res in zip(SYMBOLS, results):
        if isinstance(res, BaseException):
            logger.warning(f"美股 {sym} 抓取失敗：{res}")
            continue
        q = _to_quote(sym, display, cat, res)
        if q is None:
            logger.warning(f"美股 {sym} meta 欄位不全，略過")
            continue
        quotes.append(q)
        if session_date is None:
            session_date = _session_date_from_meta(res)

    if not quotes:
        logger.warning("美股全部 ticker 抓取失敗，將跳過 market 段的美股引子")
        return None

    snapshot = USMarketSnapshot(
        session_date=session_date or date.today(),
        quotes=quotes,
    )
    logger.success(
        f"美股昨夜抓取完成（session={snapshot.session_date}，{len(quotes)}/{len(SYMBOLS)} 檔）"
    )
    return snapshot


if __name__ == "__main__":
    snap = asyncio.run(fetch_us_market_overnight())
    if snap:
        print(f"Session: {snap.session_date}")
        for q in snap.quotes:
            sign = "+" if q.change >= 0 else ""
            print(f"  {q.display_name}({q.symbol})  {q.close:.2f}  {sign}{q.change_pct:.2f}%")
