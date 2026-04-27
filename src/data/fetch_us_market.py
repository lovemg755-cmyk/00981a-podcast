"""抓最近一個「已收盤」交易日的美股表現，給講稿 market 段當引子。

來源：Yahoo Finance v8 chart endpoint（無需 API key、JSON 結構穩定）。
為了與既有風格一致，使用 httpx + tenacity，不引入 yfinance/pandas 依賴。

關鍵設計：**永遠取最後一根「已完整收盤」的 daily bar**，避免在美股
盤中執行時抓到即時盤中價（Yahoo 的 meta.regularMarketPrice 在盤中
是 live 價，會讓「昨夜美股」變成「即時盤中」）。判斷邏輯：

  - 該 bar 的 NY 日期早於今天 NY 日期 → 已收盤 ✓
  - 該 bar 的 NY 日期等於今天 → 看 currentTradingPeriod.regular.end，
    若 now < end 表示今日盤中，跳過該根；若 now >= end 表示盤後，可用

整支 fetcher 失敗時 graceful return None，由 main pipeline 略過 — 美股不是
00981A 節目的主軸，缺漏不應阻斷產製流程。
"""
from __future__ import annotations

import asyncio
import time
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
    """抓單一 ticker 最近 5 天的 daily bars + meta。回傳整個 result 區塊。"""
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
    return results[0]


def _pick_last_closed_bar(result: dict, *, now_ts: int | None = None) -> tuple[float, float, date]:
    """從 chart result 挑出最近一根『已完整收盤』的 daily bar。

    回傳 (close, prev_close, session_date)，prev_close 是該 bar 的前一根。
    若有效 bar 不足 2 根則 raise。

    判斷『已收盤』的規則：
      - bar 的 NY 日期 < 今日 NY 日期 → 一律算已收盤
      - bar 的 NY 日期 == 今日 NY 日期 → 看 currentTradingPeriod.regular.end，
        now >= end 才算已收盤（即盤後）
    """
    if now_ts is None:
        now_ts = int(time.time())
    now_ny_date = datetime.fromtimestamp(now_ts, tz=timezone.utc).astimezone(NY).date()

    timestamps: list[int] = result.get("timestamp") or []
    quote_block = (result.get("indicators", {}).get("quote") or [{}])[0]
    closes: list[float | None] = quote_block.get("close") or []
    if not timestamps or not closes or len(timestamps) != len(closes):
        raise RuntimeError("Yahoo 回傳的 timestamp / close 陣列為空或長度不一致")

    period_end = (
        ((result.get("meta") or {}).get("currentTradingPeriod") or {}).get("regular") or {}
    ).get("end")

    period_end_ny_date: date | None = None
    if period_end:
        period_end_ny_date = (
            datetime.fromtimestamp(period_end, tz=timezone.utc).astimezone(NY).date()
        )

    def is_closed(bar_ts: int) -> bool:
        bar_ny = datetime.fromtimestamp(bar_ts, tz=timezone.utc).astimezone(NY).date()
        if bar_ny < now_ny_date:
            return True
        if bar_ny > now_ny_date:
            # 不應發生（API 不會回未來 bar），保守當作未收盤
            return False
        # bar 日期 == 今日 NY：只有當 currentTradingPeriod 也指向今天，
        # 才用 now >= end 判斷；若 period_end 指向其他日期（譬如週末看到下週一的
        # session），代表今天本來就沒交易，bar 屬於前一個交易日的延伸 → 視為已收盤
        if period_end_ny_date != bar_ny:
            return True
        return bool(period_end and now_ts >= period_end)

    # 過濾：close 必須非 None 才算有效 bar
    valid: list[tuple[int, float]] = [
        (ts, float(c)) for ts, c in zip(timestamps, closes) if c is not None
    ]
    closed = [(ts, c) for ts, c in valid if is_closed(ts)]
    if len(closed) < 2:
        raise RuntimeError(
            f"已收盤 daily bars 不足 2 根（valid={len(valid)}, closed={len(closed)}）"
        )

    last_ts, last_close = closed[-1]
    _, prev_close = closed[-2]
    session_date = datetime.fromtimestamp(last_ts, tz=timezone.utc).astimezone(NY).date()
    return last_close, prev_close, session_date


def _to_quote(
    symbol: str, display: str, category: str, close: float, prev_close: float
) -> USTickerQuote | None:
    if prev_close == 0:
        return None
    change = close - prev_close
    change_pct = change / prev_close * 100
    return USTickerQuote(
        symbol=symbol,
        display_name=display,
        category=category,
        close=close,
        prev_close=prev_close,
        change=change,
        change_pct=change_pct,
    )


async def fetch_us_market_overnight() -> USMarketSnapshot | None:
    """並行抓取所有 symbols 的最近一個已收盤交易日表現；個別 ticker 失敗會略過。

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
        try:
            close, prev_close, sess = _pick_last_closed_bar(res)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"美股 {sym} 解析失敗：{exc}")
            continue
        q = _to_quote(sym, display, cat, close, prev_close)
        if q is None:
            logger.warning(f"美股 {sym} prev_close=0，略過")
            continue
        quotes.append(q)
        # session_date 取第一個成功 ticker 的，理論上所有 ticker 同步
        if session_date is None:
            session_date = sess

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
            print(
                f"  {q.display_name}({q.symbol})  "
                f"close={q.close:.2f}  prev={q.prev_close:.2f}  {sign}{q.change_pct:.2f}%"
            )
