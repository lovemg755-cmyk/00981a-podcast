"""用 Claude Sonnet 4.6 把每日持股簡報轉成 Podcast 講稿。"""
from __future__ import annotations

import json
from pathlib import Path

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from ..data.models import DailyBrief
from ..utils.config import Settings
from ..utils.logger import logger

PROMPT_PATH = Path(__file__).parent / "prompt_template.md"


class ScriptSegment(BaseModel):
    segment: str
    text: str


class PodcastScript(BaseModel):
    title: str
    description: str
    script_segments: list[ScriptSegment]

    @property
    def full_text(self) -> str:
        return "\n\n".join(seg.text for seg in self.script_segments)

    @property
    def char_count(self) -> int:
        return len(self.full_text)


def _format_brief_for_llm(brief: DailyBrief) -> str:
    """把 DailyBrief 轉成給 LLM 的緊湊文字描述。"""
    lines = [
        f"分析交易日：{brief.date.isoformat()}（節目發布為其後第一個工作日早上 7:00）",
        f"基金：00981A 統一台股增長主動式 ETF",
        f"當日持股檔數：{len(brief.snapshot_today.holdings)}",
    ]
    if brief.quote:
        q = brief.quote
        sign = "+" if q.change >= 0 else ""
        lines.extend([
            "",
            "## 00981A 昨日（最近交易日）股價",
            f"- 交易日：{q.date.isoformat()}",
            f"- 開盤：{q.open:.2f} 元",
            f"- 最高：{q.high:.2f} 元",
            f"- 最低：{q.low:.2f} 元",
            f"- 收盤：{q.close:.2f} 元",
            f"- 漲跌：{sign}{q.change:.2f} 元（{sign}{q.change_pct:.2f}%）",
            f"- 前一交易日收盤：{q.prev_close:.2f} 元",
            f"- 成交量：{q.volume / 1000:,.0f} 千股",
        ])
    if brief.benchmark:
        bm = brief.benchmark
        lines.extend([
            "",
            f"## 主動偏離分析（{bm.target_etf} vs {bm.benchmark_etf}）",
            f"- {bm.target_etf} 前 10 大集中度：{bm.target_top10_concentration:.1f}%",
            f"- {bm.benchmark_etf} 前 10 大集中度：{bm.benchmark_top10_concentration:.1f}%",
            "",
            "### 主動偏離 top 8（依 |權重差| 排序）",
        ])
        kind_label = {
            "overweight": "Overweight 加碼",
            "underweight": "Underweight 減碼",
            "alpha_only": "Alpha 來源（0050 沒有）",
            "missing": "主動避開（0050 有但 00981A 沒有）",
        }
        for d in bm.deviations:
            sign = "+" if d.delta >= 0 else ""
            lines.append(
                f"- [{kind_label[d.kind]}] {d.name}({d.ticker})："
                f"00981A {d.weight_target:.2f}% vs 0050 {d.weight_benchmark:.2f}%  "
                f"(Δ{sign}{d.delta:.2f} pp)"
            )

    src = brief.snapshot_today.source
    is_full = src == "cmoney"
    lines.extend([
        "",
        f"## 持股變化事件（資料來源：{src}，{'完整持股清單' if is_full else '僅前 10 大'}）",
    ])
    if not brief.changes:
        lines.append("（今日無顯著持股變化事件）")
    for ev in brief.changes:
        if ev.kind == "new":
            label = "新建倉" if is_full else "進入前 10 大（可能新買或排名上升）"
            lines.append(
                f"- 【{label}】{ev.name}({ev.ticker})，今日權重 {ev.weight_today:.2f}%"
            )
        elif ev.kind == "exit":
            label = "出清" if is_full else "跌出前 10 大（可能減碼或排名下降）"
            lines.append(
                f"- 【{label}】{ev.name}({ev.ticker})，昨日權重 {ev.weight_yesterday:.2f}%"
            )
        else:
            label = "加碼" if ev.kind == "increase" else "減碼"
            lines.append(
                f"- 【{label}】{ev.name}({ev.ticker}) "
                f"{ev.weight_yesterday:.2f}% → {ev.weight_today:.2f}% "
                f"(Δ{ev.weight_delta:+.2f}pp)"
            )

    lines.append("")
    lines.append("## 個股催化劑（LLM 預先過濾）")
    for sb in brief.stock_briefs:
        if not sb.catalysts:
            continue
        lines.append(f"### {sb.name}({sb.ticker})")
        for c in sb.catalysts:
            lines.append(f"- {c.title}")
            if c.summary:
                lines.append(f"  • {c.summary}")

    lines.append("")
    lines.append("## 今日前 10 大持股（供開場帶過用）")
    top10 = sorted(brief.snapshot_today.holdings, key=lambda h: -h.weight)[:10]
    for h in top10:
        lines.append(f"- {h.name}({h.ticker}) {h.weight:.2f}%")
    return "\n".join(lines)


async def generate_script(
    brief: DailyBrief,
    *,
    settings: Settings | None = None,
) -> PodcastScript:
    settings = settings or Settings.load()
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    user_prompt = (
        "以下是今日素材，請依系統提示中的節目結構生成講稿並輸出 JSON：\n\n"
        + _format_brief_for_llm(brief)
    )

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    msg = await client.messages.create(
        model=settings.claude_script_model,
        max_tokens=4000,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = msg.content[0].text.strip() if msg.content else "{}"
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(f"Claude 回傳非合法 JSON：{raw[:300]}")
        raise RuntimeError("講稿 JSON 解析失敗") from exc

    script = PodcastScript.model_validate(data)
    logger.info(
        f"講稿生成完成：標題={script.title!r} 字數={script.char_count} "
        f"段數={len(script.script_segments)}"
    )
    return script


def save_script(script: PodcastScript, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "script.json"
    path.write_text(
        script.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return path
