"""驗證 compare() 三類事件偵測。"""
from __future__ import annotations

from datetime import date

from src.data.compare_holdings import compare
from src.data.models import Holding, HoldingsSnapshot


def _snap(d: str, holdings: list[tuple[str, str, float, int | None]]) -> HoldingsSnapshot:
    return HoldingsSnapshot(
        date=date.fromisoformat(d),
        holdings=[
            Holding(ticker=t, name=n, weight=w, shares=s) for t, n, w, s in holdings
        ],
        source="test",
    )


def test_new_and_exit_detected():
    yest = _snap("2026-04-24", [("2330", "台積電", 8.0, 1000)])
    today = _snap("2026-04-25", [("2454", "聯發科", 4.0, 500)])
    events = compare(today, yest)

    kinds = {e.kind for e in events}
    assert "new" in kinds and "exit" in kinds
    new_evt = next(e for e in events if e.kind == "new")
    assert new_evt.ticker == "2454"
    exit_evt = next(e for e in events if e.kind == "exit")
    assert exit_evt.ticker == "2330"


def test_significant_increase():
    yest = _snap("2026-04-24", [("2330", "台積電", 5.0, 1000)])
    today = _snap("2026-04-25", [("2330", "台積電", 6.0, 1200)])
    events = compare(today, yest)
    inc = [e for e in events if e.kind == "increase"]
    assert len(inc) == 1
    assert abs((inc[0].weight_delta or 0) - 1.0) < 1e-6


def test_below_threshold_ignored():
    yest = _snap("2026-04-24", [("2330", "台積電", 5.00, 1000)])
    today = _snap("2026-04-25", [("2330", "台積電", 5.10, 1010)])  # 0.1pp / 1%
    events = compare(today, yest)
    assert events == []


def test_top_n_limit():
    pairs_yest = [(f"100{i}", f"S{i}", 1.0, 100) for i in range(20)]
    pairs_today = [(f"100{i}", f"S{i}", 5.0 + i * 0.1, 100) for i in range(20)]
    yest = _snap("2026-04-24", pairs_yest)
    today = _snap("2026-04-25", pairs_today)
    events = compare(today, yest)
    assert len(events) <= 8
    deltas = [abs(e.weight_delta or 0) for e in events]
    assert deltas == sorted(deltas, reverse=True)


def test_cold_start_returns_empty():
    today = _snap("2026-04-25", [("2330", "台積電", 5.0, 1000)])
    assert compare(today, None) == []
