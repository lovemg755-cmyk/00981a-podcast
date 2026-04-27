"""每日 Podcast 主流程入口。

執行順序：
1. 檢查當日是否為交易日
2. 抓取今日持股 → 比對昨日 → 過濾顯著變化
3. 為變動股抓取催化劑（並用 Claude Haiku 過濾）
4. Claude Sonnet 生成講稿
5. Edge TTS 合成 + 音訊後製 + ID3
6. 上傳 R2 → 更新 RSS feed → 寫入 episodes.json
7. 通知 Discord
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import traceback
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")

from .audio.compose import compose_episode, get_duration_seconds
from .audio.tts import synthesize
from .data.compare_holdings import compare
from .data.fetch_catalysts import fetch_catalysts_batch
from .data.fetch_benchmark import compute_active_deviations, fetch_benchmark_0050
from .data.fetch_holdings import (
    fetch_holdings,
    latest_snapshot_before,
    save_snapshot,
)
from .data.fetch_price import (
    NotATradingDay,
    fetch_latest_quote,
    fetch_latest_trading_quote,
)
from .data.fetch_us_market import fetch_us_market_overnight
from .data.models import DailyBrief, DailyQuote, StockBrief
from .publish.update_rss import (
    EpisodeRecord,
    append_episode,
    regenerate_feed,
    regenerate_index_html,
)
from .publish.upload_r2 import upload_episode
from .script.generate_script import generate_script, save_script
from .utils.config import BUILD_DIR, Settings
from .utils.logger import logger
from .utils.notify import send_discord


async def run_pipeline(*, target_date: date | None = None, dry_run: bool = False) -> Path | None:
    settings = Settings.load(require_secrets=not dry_run)

    # 鎖定要分析的交易日：預設是「最近一個有 TWSE 交易資料的日期」
    # 對應「早上 7:00 跑、分析前一交易日」的設計
    if target_date is None:
        try:
            raw_quote = fetch_latest_trading_quote("00981A")
        except Exception as exc:  # noqa: BLE001
            logger.error(f"無法從 TWSE 取得最近交易日資料：{exc}")
            return None
        target_date = raw_quote.date
    else:
        # 指定日期：驗證為交易日，不是則 graceful skip
        try:
            raw_quote = fetch_latest_quote("00981A", target_date=target_date)
        except NotATradingDay as exc:
            logger.info(f"{target_date} 非交易日，跳過產製：{exc}")
            return None

    quote = DailyQuote(**raw_quote.__dict__)
    logger.info(f"=== 開始產製 {target_date} 交易日的 podcast (dry_run={dry_run}) ===")

    episode_dir = BUILD_DIR / "episodes" / target_date.isoformat()
    episode_dir.mkdir(parents=True, exist_ok=True)

    # 1. 持股
    snap_today = await fetch_holdings()
    snap_today.date = target_date  # 對齊 cron 日期
    save_snapshot(snap_today)

    snap_yest = latest_snapshot_before(target_date)
    if snap_yest is None:
        logger.warning("無昨日快照，今日為冷啟動，將跳過變化分析（仍會產出節目）")

    # 2. 比對 + 過濾顯著變化
    changes = compare(snap_today, snap_yest)
    logger.info(f"偵測到 {len(changes)} 個顯著變化事件")

    # 3. 催化劑
    catalyst_targets = [(ev.ticker, ev.name) for ev in changes]
    catalysts_map = (
        await fetch_catalysts_batch(catalyst_targets, settings=settings)
        if catalyst_targets
        else {}
    )
    stock_briefs = [
        StockBrief(
            ticker=ev.ticker,
            name=ev.name,
            change=ev,
            catalysts=catalysts_map.get(ev.ticker, []),
        )
        for ev in changes
    ]

    # 4. 對標 benchmark (0050) 抓取 + 主動偏離計算
    benchmark_comparison = None
    try:
        snap_0050 = await fetch_benchmark_0050()
        benchmark_comparison = compute_active_deviations(snap_today, snap_0050)
        logger.info(
            f"主動偏離計算完成：top10 集中度 {benchmark_comparison.target_top10_concentration:.1f}% "
            f"vs 0050 {benchmark_comparison.benchmark_top10_concentration:.1f}%"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"benchmark (0050) 抓取失敗，講稿將不含主動偏離分析：{exc}")

    # 5. 美股昨夜（給 market 段當引子，失敗則 graceful skip）
    us_market = None
    try:
        us_market = await fetch_us_market_overnight()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"美股昨夜抓取失敗，講稿將不含美股引子：{exc}")

    brief = DailyBrief(
        date=target_date,
        snapshot_today=snap_today,
        snapshot_yesterday=snap_yest,
        changes=changes,
        stock_briefs=stock_briefs,
        quote=quote,
        benchmark=benchmark_comparison,
        us_market=us_market,
    )

    # 4. 講稿
    publish_date = datetime.now(TAIPEI).date()
    logger.info(f"節目發布日（台北時區）：{publish_date}；分析交易日：{target_date}")
    script = await generate_script(brief, publish_date=publish_date, settings=settings)
    save_script(script, episode_dir)

    # 5. TTS + 後製
    narration = await synthesize(script, episode_dir, settings=settings)
    final_mp3 = compose_episode(narration, script, target_date, episode_dir, settings=settings)

    if dry_run:
        logger.warning(f"DRY RUN — 跳過 R2 上傳與 RSS 更新。final.mp3 在 {final_mp3}")
        return final_mp3

    # 6. 發布
    public_url = upload_episode(final_mp3, target_date, settings=settings)
    duration = get_duration_seconds(final_mp3)
    size_bytes = final_mp3.stat().st_size

    record = EpisodeRecord(
        date=target_date.isoformat(),
        title=script.title,
        description=script.description,
        audio_url=public_url,
        duration_sec=duration,
        size_bytes=size_bytes,
    )
    append_episode(record)
    regenerate_feed(settings=settings)
    regenerate_index_html(settings=settings)

    # 7. 通知
    send_discord(
        f"✅ 今日 Podcast 已發布\n"
        f"標題：{script.title}\n"
        f"時長：{duration // 60} 分 {duration % 60} 秒\n"
        f"連結：{public_url}",
        settings=settings,
    )
    logger.success(f"=== 完成：{public_url} ===")
    return final_mp3


def main() -> int:
    parser = argparse.ArgumentParser(description="00981A Daily Podcast Pipeline")
    parser.add_argument("--date", help="目標日期 YYYY-MM-DD，預設今天")
    parser.add_argument("--dry-run", action="store_true", help="不上傳、不更新 RSS")
    args = parser.parse_args()

    target = date.fromisoformat(args.date) if args.date else None
    settings_for_dry = Settings.load(require_secrets=False)
    dry_run = args.dry_run or settings_for_dry.dry_run

    try:
        asyncio.run(run_pipeline(target_date=target, dry_run=dry_run))
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.error(f"主流程失敗：{exc}\n{traceback.format_exc()}")
        if not dry_run:
            send_discord(f"❌ Podcast 產製失敗：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
