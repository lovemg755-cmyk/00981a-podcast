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


DeviationKind = Literal["overweight", "underweight", "alpha_only", "missing"]


class ActiveDeviation(BaseModel):
    """單檔股票相對 benchmark 的權重偏離。

    - overweight：兩家都持有，但 00981A 配置高於 0050
    - underweight：兩家都持有，但 00981A 配置低於 0050
    - alpha_only：只有 00981A 持有，0050 沒有 → 純 alpha 來源
    - missing：只有 0050 持有，00981A 沒有 → 主動避開
    """

    ticker: str
    name: str
    weight_target: float       # 在 00981A 的權重（沒持有則 0）
    weight_benchmark: float    # 在 0050 的權重（沒持有則 0）
    delta: float               # weight_target - weight_benchmark（百分點差）
    kind: DeviationKind


class BenchmarkComparison(BaseModel):
    target_etf: str = "00981A"
    benchmark_etf: str = "0050"
    deviations: list[ActiveDeviation]
    target_top10_concentration: float    # 00981A 前 10 大合計權重
    benchmark_top10_concentration: float  # 0050 前 10 大合計權重


class USTickerQuote(BaseModel):
    """美股單一指數或個股的昨夜表現（給講稿 market 段引用）。"""

    symbol: str                # Yahoo symbol，例如 "^GSPC"、"NVDA"
    display_name: str          # 中文/可朗讀名稱，例如 "費城半導體指數"
    category: Literal["index", "stock"]
    close: float
    prev_close: float
    change: float              # close - prev_close（價格單位）
    change_pct: float          # 漲跌幅百分比


class USMarketSnapshot(BaseModel):
    """昨夜美股快照：包含主要指數與 00981A 相關 AI 供應鏈權值股。"""

    session_date: date         # 美股最近一個收盤日（紐約時區）
    quotes: list[USTickerQuote]


class DailyBrief(BaseModel):
    date: date
    snapshot_today: HoldingsSnapshot
    snapshot_yesterday: HoldingsSnapshot | None
    changes: list[ChangeEvent]
    stock_briefs: list[StockBrief]
    quote: DailyQuote | None = None
    benchmark: BenchmarkComparison | None = None
    us_market: USMarketSnapshot | None = None
