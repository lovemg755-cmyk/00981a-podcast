"""抓取 00981A 每日持股，多來源 fallback。

主要來源：MoneyDJ（前 10 大持股，靜態 HTML，最穩定）
備援來源：Yahoo Stock（regex 解析）
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date, datetime
from pathlib import Path

import httpx
from selectolax.parser import HTMLParser
from tenacity import retry, stop_after_attempt, wait_exponential

from ..utils.config import HOLDINGS_DIR
from ..utils.logger import logger
from .models import Holding, HoldingsSnapshot

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9"}


_NUM_RE = re.compile(r"-?\d[\d,]*\.?\d*")
# 例：「台積電(2330.TW)」「鴻海-KY(3665.TW)」
_NAME_TICKER_RE = re.compile(r"^(.+?)\(([0-9A-Z]{4,6})\.TW[OW]?\)\s*$")


def _to_float(text: str) -> float | None:
    if text is None:
        return None
    m = _NUM_RE.search(text.replace(",", ""))
    return float(m.group()) if m else None


def _to_int(text: str) -> int | None:
    f = _to_float(text)
    return int(f) if f is not None else None


def _today() -> date:
    return datetime.now().date()


# ---------- 主要來源：MoneyDJ ----------

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
async def fetch_from_moneydj(client: httpx.AsyncClient) -> HoldingsSnapshot:
    """MoneyDJ ETF 持股頁。

    結構：tables[i] 含 header ['個股名稱','持股比率(%)','持股股數']，row 為
    ['台積電(2330.TW)', '9.39', '9,114,000.00']。
    """
    url = "https://www.moneydj.com/ETF/X/Basic/Basic0007.xdjhtm?etfid=00981a.tw"
    resp = await client.get(url, headers=HEADERS, timeout=20.0)
    resp.raise_for_status()
    tree = HTMLParser(resp.text)

    holdings: list[Holding] = []
    for t in tree.css("table"):
        rows = t.css("tr")
        if len(rows) < 3:
            continue
        # 看 header 是否含「個股名稱」+「投資比例」/「比例」
        # MoneyDJ 實際 header：個股名稱 | 投資比例(%) | 持有股數
        head_cells = [c.text(strip=True) for c in rows[0].css("td, th")]
        head_text = "".join(head_cells)
        if "個股名稱" not in head_text:
            continue
        if not any(kw in head_text for kw in ("投資比例", "比例", "持股", "持有股")):
            continue
        # 解析 data rows
        for r in rows[1:]:
            cells = [c.text(strip=True) for c in r.css("td, th")]
            if len(cells) < 3:
                continue
            m = _NAME_TICKER_RE.match(cells[0])
            if not m:
                continue
            name = m.group(1).strip()
            ticker = m.group(2)
            weight = _to_float(cells[1])
            shares = _to_int(cells[2])
            if weight is None or weight <= 0:
                continue
            holdings.append(Holding(ticker=ticker, name=name, weight=weight, shares=shares))
        break

    if not holdings:
        raise ValueError("MoneyDJ 找不到持股表，可能改版")

    return HoldingsSnapshot(
        date=_today(),
        fund_code="00981A",
        holdings=holdings,
        source="moneydj",
    )


# ---------- 主入口 ----------

async def fetch_holdings() -> HoldingsSnapshot:
    """目前僅用 MoneyDJ（前 10 大持股）。

    Yahoo / cmoney / pocket 為 SPA 動態載入，pure HTML 抓不到正確資料；
    若想取得全持股名單，未來可逆向 cmoney/pocket 的 client-side API。
    """
    sources = [
        ("moneydj", fetch_from_moneydj),
    ]
    last_exc: Exception | None = None
    async with httpx.AsyncClient(follow_redirects=True) as client:
        for name, fn in sources:
            try:
                logger.info(f"嘗試從 {name} 抓取 00981A 持股…")
                snap = await fn(client)
                logger.success(f"{name} 成功，共 {len(snap.holdings)} 檔持股")
                return snap
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"{name} 失敗: {exc}")
                last_exc = exc
                continue
    raise RuntimeError(f"所有來源皆失敗，最後錯誤: {last_exc}")


def save_snapshot(snap: HoldingsSnapshot) -> Path:
    HOLDINGS_DIR.mkdir(parents=True, exist_ok=True)
    path = HOLDINGS_DIR / f"{snap.date.isoformat()}.json"
    path.write_text(
        json.dumps(snap.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"持股快照已寫入 {path}")
    return path


def load_snapshot(target_date: date) -> HoldingsSnapshot | None:
    path = HOLDINGS_DIR / f"{target_date.isoformat()}.json"
    if not path.exists():
        return None
    return HoldingsSnapshot.model_validate_json(path.read_text(encoding="utf-8"))


def latest_snapshot_before(target_date: date) -> HoldingsSnapshot | None:
    if not HOLDINGS_DIR.exists():
        return None
    files = sorted(HOLDINGS_DIR.glob("*.json"), reverse=True)
    for f in files:
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        if d < target_date:
            return HoldingsSnapshot.model_validate_json(f.read_text(encoding="utf-8"))
    return None


if __name__ == "__main__":
    snap = asyncio.run(fetch_holdings())
    save_snapshot(snap)
    print(f"來源={snap.source}, 持股檔數={len(snap.holdings)}")
    for h in snap.holdings[:10]:
        print(f"  {h.ticker} {h.name:8s}  {h.weight}%  {h.shares}")
