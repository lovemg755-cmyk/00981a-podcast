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
SILENCE_BETWEEN_SEGMENTS_MS = 600
# 句子間額外停頓（用 SSML break 模擬）
_SENTENCE_END = re.compile(r"([。！？\n])")


def _add_breathing_pauses(text: str) -> str:
    """在句尾加上短停頓，讓朗讀更自然。Edge TTS 接受 SSML，但純文字模式
    透過標點密度即可。這裡保留純文字，僅整理多餘空白。"""
    text = text.replace("\r", "").strip()
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


def _concat_mp3s(parts: list[Path], output: Path) -> None:
    """用 pydub 串接多個 mp3，段間插入靜音。"""
    from pydub import AudioSegment  # 延遲匯入

    silence = AudioSegment.silent(duration=SILENCE_BETWEEN_SEGMENTS_MS)
    combined: AudioSegment | None = None
    for p in parts:
        seg = AudioSegment.from_mp3(p)
        combined = seg if combined is None else combined + silence + seg
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
