"""用 Playwright 渲染 CMoney SPA，抓 00981A 完整持股清單。

CMoney 的 ETF 持股頁是 Vue/Nuxt SPA，靜態 HTML 沒有資料，必須執行 JS 才能取得。
此模組用 Playwright headless chromium 渲染後抽取個股表格，可拿到 50+ 檔完整持股
（不只 MoneyDJ 的前 10 大）。
"""
from __future__ import annotations

import asyncio
import re
from datetime import datetime

from playwright.async_api import async_playwright

from ..utils.logger import logger
from .models import Holding, HoldingsSnapshot

# 個股代號：純數字 4-6 碼（容許 KY 後綴的「-KY」前段）
_TICKER_RE = re.compile(r"^[0-9]{4,6}[A-Z]?$")
# 排除權重低於此門檻的尾部部位（可能是清倉中的殘餘）
_MIN_WEIGHT = 0.01


async def fetch_full_holdings_cmoney(
    fund_code: str = "00981A",
    *,
    timeout_ms: int = 30000,
) -> HoldingsSnapshot:
    """用 Playwright 從 CMoney 抓完整持股。

    解析邏輯：
    - CMoney 有兩個 table：第一個是「產業占比」(10 列)、第二個是「個股清單」(50+ 列)
    - 個股清單欄位：代號 | 名稱 | 權重 | 持有股數 | 類別
    - 排除非數字代號（C_NTD、M_NTD、PFUR_NTD、RDI_NTD 是現金/應付/應收）
    - 排除 weight < 0.01% 的尾部部位
    """
    url = f"https://www.cmoney.tw/etf/tw/{fund_code}/fundholding"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            ctx = await browser.new_context(
                locale="zh-TW",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/130.0 Safari/537.36"
                ),
            )
            page = await ctx.new_page()
            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            await page.wait_for_selector("table", timeout=timeout_ms)

            tables = await page.query_selector_all("table")
            holdings_table = None
            for t in tables:
                rows = await t.query_selector_all("tr")
                if len(rows) >= 20:  # 完整持股表通常 50+ 列；產業占比表 10 列以下
                    holdings_table = t
                    break
            if not holdings_table:
                raise RuntimeError(
                    f"CMoney 找不到完整持股表（rows >= 20），共 {len(tables)} 個 table"
                )

            rows = await holdings_table.query_selector_all("tr")
            holdings: list[Holding] = []
            for row in rows[1:]:  # 跳過 header
                cells = await row.query_selector_all("td, th")
                if len(cells) < 4:
                    continue
                texts = [(await c.inner_text()).strip() for c in cells]
                ticker, name = texts[0], texts[1]
                weight_str, shares_str = texts[2], texts[3]

                if not _TICKER_RE.match(ticker):
                    continue  # 排除 C_NTD / M_NTD / PFUR_NTD / RDI_NTD

                weight_m = re.search(r"(-?\d+\.\d+)", weight_str.replace(",", ""))
                if not weight_m:
                    continue
                weight = float(weight_m.group())
                if weight < _MIN_WEIGHT:
                    continue

                shares_m = re.search(r"-?\d[\d,]*", shares_str)
                shares = int(shares_m.group().replace(",", "")) if shares_m else None

                holdings.append(Holding(
                    ticker=ticker, name=name, weight=weight, shares=shares,
                ))

            if not holdings:
                raise RuntimeError("CMoney 解析完成後無任何有效個股")

            holdings.sort(key=lambda h: -h.weight)
            logger.success(
                f"CMoney 完整持股抓取成功：{len(holdings)} 檔，"
                f"top1={holdings[0].name}({holdings[0].ticker}) {holdings[0].weight}%"
            )
            return HoldingsSnapshot(
                date=datetime.now().date(),
                fund_code=fund_code.upper(),
                holdings=holdings,
                source="cmoney",
            )
        finally:
            await browser.close()


if __name__ == "__main__":
    snap = asyncio.run(fetch_full_holdings_cmoney())
    print(f"來源={snap.source}, 共 {len(snap.holdings)} 檔")
    print(f"前 10 大合計：{sum(h.weight for h in snap.holdings[:10]):.2f}%")
    print(f"全部合計：{sum(h.weight for h in snap.holdings):.2f}%")
    for h in snap.holdings:
        s = f"{h.shares:,}" if h.shares else "-"
        print(f"  {h.ticker:6s} {h.name:10s}  {h.weight:6.2f}%  {s}")
