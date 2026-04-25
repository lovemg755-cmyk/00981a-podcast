"""Edge TTS 包裝：把 PodcastScript 轉成單一 narration.mp3。"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import edge_tts
from tenacity import retry, stop_after_attempt, wait_exponential

from ..script.generate_script import PodcastScript
from ..utils.config import Settings
from ..utils.logger import logger

# 段落間靜音（毫秒）
SILENCE_BETWEEN_SEGMENTS_MS = 800
# 段落拼接時的 cross-fade（毫秒），消除接縫突兀感
SEGMENT_CROSSFADE_MS = 30
# 句子間額外停頓（用 SSML break 模擬）
_SENTENCE_END = re.compile(r"([。！？\n])")


def _add_breathing_pauses(text: str) -> str:
    """準備餵給 Edge TTS 的純文字。

    1. 移除所有 Markdown 格式符號（** _ ~ ` 等），避免 TTS 念出「星號星號」
    2. 也移除單一 *（用於股票名稱如「巨*」），避免「巨星號」念法
    3. 把破折號 — 換成逗號，讓停頓更自然
    4. 整理空白
    """
    text = text.replace("\r", "").strip()
    # Markdown 符號 → 完全移除
    text = re.sub(r"\*+", "", text)   # 移除 ** 與 *（含股票名稱中的星號）
    text = re.sub(r"_{2,}", "", text)  # 移除 __ 多重底線（保留中文底線變體）
    text = re.sub(r"~+", "", text)    # 移除 ~~ 與 ~
    text = re.sub(r"`+", "", text)    # 移除 ` 與 ```
    # 破折號 → 逗號（自然停頓）
    text = text.replace("——", "，")
    text = text.replace("—", "，")
    # 多餘空白
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def _synthesize_one(text: str, voice: str, rate: str, pitch: str, out: Path) -> None:
    communicate = edge_tts.Communicate(
        text=text,
        voice=voice,
        rate=rate,
        pitch=pitch,
    )
    await communicate.save(str(out))
    if not out.exists() or out.stat().st_size < 1024:
        raise RuntimeError(f"TTS 輸出檔過小或不存在：{out}")


async def synthesize(
    script: PodcastScript,
    out_dir: Path,
    *,
    settings: Settings | None = None,
) -> Path:
    """逐段合成後拼接，回傳 narration.mp3 路徑。"""
    settings = settings or Settings.load(require_secrets=False)
    out_dir.mkdir(parents=True, exist_ok=True)

    segment_files: list[Path] = []
    for i, seg in enumerate(script.script_segments):
        text = _add_breathing_pauses(seg.text)
        if not text:
            continue
        seg_path = out_dir / f"seg_{i:02d}_{seg.segment}.mp3"
        logger.info(
            f"TTS 合成第 {i+1}/{len(script.script_segments)} 段 "
            f"({seg.segment}, {len(text)} 字)…"
        )
        await _synthesize_one(
            text, settings.tts_voice, settings.tts_rate, settings.tts_pitch, seg_path
        )
        segment_files.append(seg_path)

    if not segment_files:
        raise RuntimeError("無任何可合成的段落")

    narration = out_dir / "narration.mp3"
    _concat_mp3s(segment_files, narration)
    logger.success(f"narration.mp3 已生成：{narration}")
    return narration


def _trim_silence(seg, threshold_db: int = -45):
    """裁掉每段首尾的死寂（保留 30ms 自然氣口）。"""
    from pydub.silence import detect_leading_silence
    lead = detect_leading_silence(seg, silence_threshold=threshold_db)
    tail = detect_leading_silence(seg.reverse(), silence_threshold=threshold_db)
    lead = max(0, lead - 30)  # 留 30ms 自然氣口
    tail = max(0, tail - 30)
    return seg[lead : len(seg) - tail]


def _concat_mp3s(parts: list[Path], output: Path) -> None:
    """串接多段 mp3：每段先裁掉首尾死寂，段間 800ms 靜音 + 30ms cross-fade。"""
    from pydub import AudioSegment  # 延遲匯入

    silence = AudioSegment.silent(duration=SILENCE_BETWEEN_SEGMENTS_MS)
    combined: AudioSegment | None = None
    for p in parts:
        seg = AudioSegment.from_mp3(p)
        seg = _trim_silence(seg)
        if combined is None:
            combined = seg
        else:
            # 用 append + crossfade 讓接縫平順
            combined = combined.append(silence, crossfade=0)
            combined = combined.append(seg, crossfade=SEGMENT_CROSSFADE_MS)
    assert combined is not None
    combined.export(output, format="mp3", bitrate="128k")


# CLI 預覽
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--out", default="preview.mp3")
    parser.add_argument("--voice", default="zh-TW-HsiaoChenNeural")
    args = parser.parse_args()

    async def _run():
        await _synthesize_one(args.text, args.voice, "+0%", "+0Hz", Path(args.out))
        print(f"已輸出 {args.out}")

    asyncio.run(_run())
