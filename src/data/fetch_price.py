"""抓 00981A 最近一個交易日的開高低收與漲跌幅。

來源：TWSE 官方 STOCK_DAY API（開放資料、最權威、不需 key）。
備援：twstock 套件（背後也是 TWSE，但有快取與舊資料儲存）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import httpx
from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from ..utils.logger import logger

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


class NotATradingDay(ValueError):
    """指定日期不是台股交易日（週末、假日、停盤等）。

    與其他 ValueError 區分，讓 main pipeline 可以 graceful skip 而不誤判為錯誤。
    """


@dataclass(frozen=True)
class DailyQuote:
    date: date
    open: float
    high: float
    low: float
    close: float
    change: float          # 與前一交易日收盤相比
    change_pct: float      # 漲跌幅（%）
    volume: int            # 成交股數
    prev_close: float      # 前一交易日收盤

    @property
    def headline(self) -> str:
        sign = "+" if self.change >= 0 else ""
        return (
            f"{self.date:%m/%d} 收 {self.close:.2f}，"
            f"{sign}{self.change:.2f}（{sign}{self.change_pct:.2f}%）"
        )


def _roc_to_iso(roc_date: str) -> date:
    """『115/04/24』 → date(2026, 4, 24)。"""
    parts = roc_date.split("/")
    return date(int(parts[0]) + 1911, int(parts[1]), int(parts[2]))


def _to_float(s: str) -> float:
    return float(s.replace(",", "").replace("+", ""))


def _to_int(s: str) -> int:
    return int(_to_float(s))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=8),
    retry=retry_if_not_exception_type(NotATradingDay),
)
def fetch_latest_quote(
    fund_code: str = "00981A",
    *,
    target_date: date | None = None,
) -> DailyQuote:
    """回傳該基金的單日報價。

    target_date：
    - None → 抓最新交易日（取該月最後一筆）。
    - 指定日期 → 抓該日報價；該日非交易日則 raise。
    """
    query_month = (target_date or date.today())
    url = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"
    params = {
        "response": "json",
        "date": query_month.strftime("%Y%m01"),
        "stockNo": fund_code,
    }
    r = httpx.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=20.0)
    r.raise_for_status()
    j = r.json()
    if j.get("stat") != "OK":
        raise ValueError(f"TWSE 回應 stat={j.get('stat')}: {j.get('title')}")

    fields: list[str] = j.get("fields", [])
    rows: list[list[str]] = j.get("data", [])
    if not rows:
        raise NotATradingDay(
            f"TWSE {query_month.strftime('%Y/%m')} 該月份無 {fund_code} 交易資料"
        )

    idx = {name: fields.index(name) for name in fields}

    # 選用 row：指定日期或最後一筆
    if target_date is not None:
        target_row = None
        for row in rows:
            if _roc_to_iso(row[idx["日期"]]) == target_date:
                target_row = row
                break
        if target_row is None:
            raise NotATradingDay(
                f"TWSE 無 {target_date} 的交易資料（週末、假日、或盤前查詢）"
            )
    else:
        target_row = rows[-1]

    quote_date = _roc_to_iso(target_row[idx["日期"]])
    close = _to_float(target_row[idx["收盤價"]])
    change = _to_float(target_row[idx["漲跌價差"]])
    open_ = _to_float(target_row[idx["開盤價"]])
    high = _to_float(target_row[idx["最高價"]])
    low = _to_float(target_row[idx["最低價"]])
    volume = _to_int(target_row[idx["成交股數"]])

    prev_close = close - change
    change_pct = (change / prev_close * 100) if prev_close > 0 else 0.0

    quote = DailyQuote(
        date=quote_date,
        open=open_,
        high=high,
        low=low,
        close=close,
        change=change,
        change_pct=change_pct,
        volume=volume,
        prev_close=prev_close,
    )
    logger.info(f"{fund_code} 報價：{quote.headline}")
    return quote


def fetch_latest_trading_quote(
    fund_code: str = "00981A",
    *,
    end_date: date | None = None,
    max_lookback: int = 14,
) -> DailyQuote:
    """從 end_date 往前推，找出最近一個有交易資料的日期。

    用於「今天早上跑，分析最近交易日」的情境：
    - 週一早上跑 → end_date=週一 → 往前推到上週五
    - 一般週中早上跑 → end_date=今天 → 往前推到昨天
    - 春節後第一天 → 往前推可能 5+ 天才找到
    """
    from datetime import timedelta

    end_date = end_date or date.today()
    last_exc: Exception | None = None
    for offset in range(max_lookback):
        candidate = end_date - timedelta(days=offset)
        try:
            return fetch_latest_quote(fund_code, target_date=candidate)
        except NotATradingDay as exc:
            last_exc = exc
            continue
    raise RuntimeError(
        f"從 {end_date} 往前 {max_lookback} 天找不到 {fund_code} 的交易資料：{last_exc}"
    )


if __name__ == "__main__":
    q = fetch_latest_trading_quote()
    print(q.headline)
