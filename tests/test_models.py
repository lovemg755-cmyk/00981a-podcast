"""模型基本驗證。"""
from __future__ import annotations

from datetime import date

from src.data.models import ChangeEvent, Holding, HoldingsSnapshot


def test_holdings_snapshot_by_ticker():
    snap = HoldingsSnapshot(
        date=date(2026, 4, 25),
        holdings=[
            Holding(ticker="2330", name="台積電", weight=8.0),
            Holding(ticker="2454", name="聯發科", weight=4.0),
        ],
        source="test",
    )
    m = snap.by_ticker()
    assert set(m.keys()) == {"2330", "2454"}
    assert m["2330"].name == "台積電"


def test_change_event_headline():
    ev = ChangeEvent(kind="new", ticker="2330", name="台積電", weight_today=8.0)
    assert "新進" in ev.headline
    assert "2330" in ev.headline
