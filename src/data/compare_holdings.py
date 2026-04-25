"""比對兩日持股快照，輸出變化事件。"""
from __future__ import annotations

from .models import ChangeEvent, HoldingsSnapshot

# 顯著變化門檻
WEIGHT_DELTA_THRESHOLD = 0.3  # 權重變化超過 ±0.3 個百分點視為顯著
SHARES_DELTA_PCT_THRESHOLD = 20.0  # 股數變化超過 ±20% 視為顯著
TOP_N = 8  # 每日最多取 N 個變化事件


def compare(
    today: HoldingsSnapshot,
    yesterday: HoldingsSnapshot | None,
) -> list[ChangeEvent]:
    """回傳依「重要性」排序的變化事件清單，最多 TOP_N 筆。

    重要性 = |權重變化|（new/exit 視為等同 100% 權重變化）
    """
    if yesterday is None:
        return []
    # source 不一致時禁止比對（例如 cmoney 48 檔 vs moneydj 10 檔會誤判一堆假變化）
    if today.source != yesterday.source:
        from ..utils.logger import logger
        logger.warning(
            f"資料來源不一致（today={today.source} vs yesterday={yesterday.source}），"
            f"跳過 changes 比對以避免假變化"
        )
        return []

    today_map = today.by_ticker()
    yest_map = yesterday.by_ticker()

    events: list[ChangeEvent] = []

    # 1. 新進股
    for ticker, h in today_map.items():
        if ticker not in yest_map:
            events.append(
                ChangeEvent(
                    kind="new",
                    ticker=ticker,
                    name=h.name,
                    weight_today=h.weight,
                    weight_yesterday=0.0,
                    weight_delta=h.weight,
                    shares_today=h.shares,
                )
            )

    # 2. 出清股
    for ticker, h in yest_map.items():
        if ticker not in today_map:
            events.append(
                ChangeEvent(
                    kind="exit",
                    ticker=ticker,
                    name=h.name,
                    weight_today=0.0,
                    weight_yesterday=h.weight,
                    weight_delta=-h.weight,
                    shares_yesterday=h.shares,
                )
            )

    # 3. 顯著加減碼
    for ticker, h_today in today_map.items():
        if ticker not in yest_map:
            continue
        h_yest = yest_map[ticker]
        weight_delta = h_today.weight - h_yest.weight
        shares_delta_pct: float | None = None
        if h_today.shares and h_yest.shares:
            if h_yest.shares > 0:
                shares_delta_pct = (h_today.shares - h_yest.shares) / h_yest.shares * 100

        is_significant_weight = abs(weight_delta) >= WEIGHT_DELTA_THRESHOLD
        is_significant_shares = (
            shares_delta_pct is not None
            and abs(shares_delta_pct) >= SHARES_DELTA_PCT_THRESHOLD
        )
        if not (is_significant_weight or is_significant_shares):
            continue

        kind = "increase" if weight_delta > 0 else "decrease"
        events.append(
            ChangeEvent(
                kind=kind,
                ticker=ticker,
                name=h_today.name,
                weight_today=h_today.weight,
                weight_yesterday=h_yest.weight,
                weight_delta=weight_delta,
                shares_today=h_today.shares,
                shares_yesterday=h_yest.shares,
                shares_delta_pct=shares_delta_pct,
            )
        )

    # 依重要性排序，截 TOP_N
    events.sort(key=lambda e: abs(e.weight_delta or 0), reverse=True)
    return events[:TOP_N]
