"""驗證 _pick_last_closed_bar 在不同執行時刻都能挑到『最近一個已收盤』的 bar。

關鍵風險：在美股盤中執行時，Yahoo 回傳的最新 bar 是 partial（close 是即時價），
不能當作『昨夜美股』使用——必須跳到前一根。

固定一份 fixture（5 根模擬的 daily bars，最後一根是『週一』），
然後用不同的 fake now_ts 跑邏輯，預期挑到正確的 bar。
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from src.data.fetch_us_market import _pick_last_closed_bar

NY = ZoneInfo("America/New_York")


def _ny_session_open(d: date) -> int:
    """模擬 Yahoo 的 daily bar timestamp：紐約當地 9:30 AM 開盤的 unix 秒。"""
    return int(datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY).timestamp())


def _ny_session_close(d: date) -> int:
    """模擬 currentTradingPeriod.regular.end：紐約當地 16:00 收盤的 unix 秒。"""
    return int(datetime(d.year, d.month, d.day, 16, 0, tzinfo=NY).timestamp())


def _ny_time(d: date, hour: int, minute: int = 0) -> int:
    return int(datetime(d.year, d.month, d.day, hour, minute, tzinfo=NY).timestamp())


# 5 根 bar：4/20(一)、4/21(二)、4/22(三)、4/23(四)、4/24(五)
SESSIONS = [date(2026, 4, d) for d in (20, 21, 22, 23, 24)]
CLOSES = [100.0, 101.0, 102.0, 103.0, 110.0]  # 週五 +6.8%
TIMESTAMPS = [_ny_session_open(d) for d in SESSIONS]


def _make_result(*, current_period_date: date) -> dict:
    """組一個假的 Yahoo chart result，currentTradingPeriod 指向給定日期。"""
    return {
        "meta": {
            "currentTradingPeriod": {
                "regular": {
                    "start": _ny_session_open(current_period_date),
                    "end": _ny_session_close(current_period_date),
                },
            },
        },
        "timestamp": TIMESTAMPS,
        "indicators": {"quote": [{"close": CLOSES}]},
    }


def test_picks_last_completed_when_run_after_close():
    """週五紐約 18:00 跑：週五 session 已結束 → 挑週五 bar。"""
    result = _make_result(current_period_date=date(2026, 4, 24))
    now = _ny_time(date(2026, 4, 24), 18, 0)
    close, prev, sess = _pick_last_closed_bar(result, now_ts=now)
    assert sess == date(2026, 4, 24)
    assert close == 110.0
    assert prev == 103.0


def test_skips_partial_bar_when_run_mid_session():
    """週五紐約 11:00 盤中跑：週五 bar 還沒收盤 → 跳過，挑週四 bar。"""
    result = _make_result(current_period_date=date(2026, 4, 24))
    now = _ny_time(date(2026, 4, 24), 11, 0)
    close, prev, sess = _pick_last_closed_bar(result, now_ts=now)
    assert sess == date(2026, 4, 23)
    assert close == 103.0
    assert prev == 102.0


def test_weekend_currentperiod_pointing_to_next_monday():
    """週六上午跑（currentTradingPeriod 指向下週一）：週五 bar 已收盤 → 挑週五。

    這是真實 Yahoo 行為：週末 currentTradingPeriod 會指向下一個交易日的 session。
    若邏輯誤把『period_end 在未來』判成『今天還沒收盤』，會錯回到週四。
    """
    result = _make_result(current_period_date=date(2026, 4, 27))  # 下週一
    now = _ny_time(date(2026, 4, 25), 10, 0)  # 週六上午
    close, prev, sess = _pick_last_closed_bar(result, now_ts=now)
    assert sess == date(2026, 4, 24)
    assert close == 110.0
    assert prev == 103.0


def test_filters_out_none_close():
    """有些 bar 的 close 為 None（譬如盤中當下還沒成交）→ 應排除後再判斷。"""
    result = _make_result(current_period_date=date(2026, 4, 24))
    result["indicators"]["quote"][0]["close"] = [100.0, 101.0, 102.0, 103.0, None]
    now = _ny_time(date(2026, 4, 24), 11, 0)  # 週五盤中
    close, prev, sess = _pick_last_closed_bar(result, now_ts=now)
    # None 被排除後剩 4 根（4/20~4/23），週五 bar 是今天且未收盤所以也跳過
    # 但因為 close=None 已被過濾，所以最後一根 valid bar 是 4/23
    assert sess == date(2026, 4, 23)
    assert close == 103.0
    assert prev == 102.0


def test_raises_when_not_enough_closed_bars():
    """已收盤 bars 不足 2 根時應 raise。"""
    result = {
        "meta": {"currentTradingPeriod": {"regular": {"end": _ny_session_close(date(2026, 4, 24))}}},
        "timestamp": [_ny_session_open(date(2026, 4, 24))],
        "indicators": {"quote": [{"close": [110.0]}]},
    }
    now = _ny_time(date(2026, 4, 24), 18, 0)
    with pytest.raises(RuntimeError, match="已收盤 daily bars 不足"):
        _pick_last_closed_bar(result, now_ts=now)
