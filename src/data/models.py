"""持股、變化事件、催化劑的資料模型。"""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Holding(BaseModel):
    ticker: str = Field(description="股票代號，例如 2330")
    name: str = Field(description="股票名稱，例如 台積電")
    weight: float = Field(description="占基金資產淨值百分比 (0-100)")
    shares: int | None = Field(default=None, description="持有股數")


class HoldingsSnapshot(BaseModel):
    date: date
    fund_code: str = "00981A"
    total_nav: float | None = None
    holdings: list[Holding]
    source: str = Field(description="資料來源識別：ezmoney / cmoney / pocket")

    def by_ticker(self) -> dict[str, Holding]:
        return {h.ticker: h for h in self.holdings}


ChangeKind = Literal["new", "exit", "increase", "decrease"]


class ChangeEvent(BaseModel):
    kind: ChangeKind
    ticker: str
    name: str
    weight_today: float | None = None
    weight_yesterday: float | None = None
    weight_delta: float | None = None
    shares_today: int | None = None
    shares_yesterday: int | None = None
    shares_delta_pct: float | None = None

    @property
    def headline(self) -> str:
        labels = {
            "new": "新進",
            "exit": "出清",
            "increase": "加碼",
            "decrease": "減碼",
        }
        return f"{labels[self.kind]} {self.name}({self.ticker})"


class Catalyst(BaseModel):
    title: str
    summary: str = ""
    url: str | None = None
    published_at: str | None = None


class StockBrief(BaseModel):
    ticker: str
    name: str
    change: ChangeEvent
    catalysts: list[Catalyst] = Field(default_factory=list)


class DailyQuote(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    change: float
    change_pct: float
    volume: int
    prev_close: float


class DailyBrief(BaseModel):
    date: date
    snapshot_today: HoldingsSnapshot
    snapshot_yesterday: HoldingsSnapshot | None
    changes: list[ChangeEvent]
    stock_briefs: list[StockBrief]
    quote: DailyQuote | None = None
