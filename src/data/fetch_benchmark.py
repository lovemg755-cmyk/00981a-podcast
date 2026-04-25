"""抓取對標基準 0050 持股，計算 00981A 的主動偏離 (active deviation)。

主動偏離 = 00981A 權重 - 0050 權重，用於說明經理人 (瑤姊) 的策略押注。
"""
from __future__ import annotations

import asyncio

import httpx

from ..utils.logger import logger
from .fetch_holdings import fetch_etf_from_moneydj
from .models import ActiveDeviation, BenchmarkComparison, HoldingsSnapshot


async def fetch_benchmark_0050() -> HoldingsSnapshot:
    """抓 0050 元大台灣 50 的前 10 大持股。"""
    async with httpx.AsyncClient(follow_redirects=True) as client:
        snap = await fetch_etf_from_moneydj(client, "0050")
        logger.success(f"0050 持股抓取完成，共 {len(snap.holdings)} 檔")
        return snap


def compute_active_deviations(
    target: HoldingsSnapshot,
    benchmark: HoldingsSnapshot,
    *,
    top_n: int = 8,
) -> BenchmarkComparison:
    """計算 target (00981A) 相對 benchmark (0050) 的主動偏離。

    回傳依 |delta| 排序的前 top_n 筆偏離事件，方便講稿挑重點。
    """
    target_map = {h.ticker: h for h in target.holdings}
    bench_map = {h.ticker: h for h in benchmark.holdings}

    deviations: list[ActiveDeviation] = []

    # 1. 在 target 裡的（含兩家都有 + alpha_only）
    for tk, h in target_map.items():
        bench_h = bench_map.get(tk)
        if bench_h is None:
            deviations.append(ActiveDeviation(
                ticker=tk, name=h.name,
                weight_target=h.weight,
                weight_benchmark=0.0,
                delta=h.weight,
                kind="alpha_only",
            ))
        else:
            delta = h.weight - bench_h.weight
            deviations.append(ActiveDeviation(
                ticker=tk, name=h.name,
                weight_target=h.weight,
                weight_benchmark=bench_h.weight,
                delta=delta,
                kind="overweight" if delta > 0 else "underweight",
            ))

    # 2. 在 benchmark 但不在 target（主動避開）
    for tk, bh in bench_map.items():
        if tk not in target_map:
            deviations.append(ActiveDeviation(
                ticker=tk, name=bh.name,
                weight_target=0.0,
                weight_benchmark=bh.weight,
                delta=-bh.weight,
                kind="missing",
            ))

    # 依 |delta| 由大到小排序
    deviations.sort(key=lambda d: abs(d.delta), reverse=True)
    deviations = deviations[:top_n]

    target_top10 = sum(h.weight for h in sorted(target.holdings, key=lambda x: -x.weight)[:10])
    bench_top10 = sum(h.weight for h in sorted(benchmark.holdings, key=lambda x: -x.weight)[:10])

    return BenchmarkComparison(
        target_etf=target.fund_code,
        benchmark_etf=benchmark.fund_code,
        deviations=deviations,
        target_top10_concentration=target_top10,
        benchmark_top10_concentration=bench_top10,
    )


if __name__ == "__main__":
    snap = asyncio.run(fetch_benchmark_0050())
    print(f"來源={snap.source}, 共 {len(snap.holdings)} 檔")
    for h in snap.holdings:
        print(f"  {h.ticker} {h.name:8s}  {h.weight}%")
