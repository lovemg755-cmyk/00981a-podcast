"""音訊後製：拼接片頭/片尾、響度標準化、ID3 標籤。"""
from __future__ import annotations

import shutil
import subprocess
from datetime import date
from pathlib import Path

from mutagen.id3 import APIC, COMM, ID3, TALB, TCON, TDRC, TIT2, TPE1, TPE2
from mutagen.mp3 import MP3

from ..script.generate_script import PodcastScript
from ..utils.config import ASSETS_DIR, Settings
from ..utils.logger import logger

CROSSFADE_MS = 500
TARGET_LUFS = -16.0  # Spotify/Apple 推薦響度


def _has_ffmpeg_normalize() -> bool:
    return shutil.which("ffmpeg-normalize") is not None


def _normalize_loudness(input_path: Path, output_path: Path) -> None:
    """使用 ffmpeg-normalize 做 EBU R128 標準化。"""
    if not _has_ffmpeg_normalize():
        logger.warning("ffmpeg-normalize 未安裝，跳過響度標準化")
        shutil.copyfile(input_path, output_path)
        return
    cmd = [
        "ffmpeg-normalize",
        str(input_path),
        "-o",
        str(output_path),
        "-t",
        str(TARGET_LUFS),
        "-b:a",
        "128k",
        "-c:a",
        "libmp3lame",
        "-f",
    ]
    logger.info("執行響度標準化…")
    subprocess.run(cmd, check=True, capture_output=True)


def _merge_with_intro_outro(
    narration: Path,
    intro: Path | None,
    outro: Path | None,
    output: Path,
) -> None:
    from pydub import AudioSegment

    body = AudioSegment.from_mp3(narration)
    if intro and intro.exists():
        intro_seg = AudioSegment.from_mp3(intro)
        body = intro_seg.append(body, crossfade=CROSSFADE_MS)
    if outro and outro.exists():
        outro_seg = AudioSegment.from_mp3(outro)
        body = body.append(outro_seg, crossfade=CROSSFADE_MS)
    body.export(output, format="mp3", bitrate="128k")


def _write_id3(
    mp3_path: Path,
    *,
    title: str,
    description: str,
    pub_date: date,
    settings: Settings,
    cover_path: Path | None = None,
) -> None:
    audio = MP3(mp3_path, ID3=ID3)
    if audio.tags is None:
        audio.add_tags()
    tags = audio.tags

    tags.delall("TIT2")
    tags.delall("TPE1")
    tags.delall("TPE2")
    tags.delall("TALB")
    tags.delall("TDRC")
    tags.delall("TCON")
    tags.delall("COMM")
    tags.delall("APIC")

    tags.add(TIT2(encoding=3, text=title))
    tags.add(TPE1(encoding=3, text=settings.podcast_author))
    tags.add(TPE2(encoding=3, text=settings.podcast_author))
    tags.add(TALB(encoding=3, text=settings.podcast_title))
    tags.add(TDRC(encoding=3, text=str(pub_date)))
    tags.add(TCON(encoding=3, text="Podcast"))
    tags.add(COMM(encoding=3, lang="cht", desc="desc", text=description))

    if cover_path and cover_path.exists():
        with cover_path.open("rb") as f:
            tags.add(
                APIC(
                    encoding=3,
                    mime="image/png",
                    type=3,  # cover (front)
                    desc="cover",
                    data=f.read(),
                )
            )
    audio.save()


def compose_episode(
    narration: Path,
    script: PodcastScript,
    pub_date: date,
    out_dir: Path,
    *,
    settings: Settings | None = None,
) -> Path:
    """流程：合 intro/outro → 響度標準化 → ID3 → 回傳 final.mp3。"""
    settings = settings or Settings.load(require_secrets=False)
    out_dir.mkdir(parents=True, exist_ok=True)

    intro = ASSETS_DIR / "intro.mp3"
    outro = ASSETS_DIR / "outro.mp3"
    cover = ASSETS_DIR / "cover.png"

    merged = out_dir / "merged.mp3"
    _merge_with_intro_outro(narration, intro, outro, merged)

    final = out_dir / "final.mp3"
    _normalize_loudness(merged, final)
    merged.unlink(missing_ok=True)

    _write_id3(
        final,
        title=script.title,
        description=script.description,
        pub_date=pub_date,
        settings=settings,
        cover_path=cover if cover.exists() else None,
    )
    logger.success(f"final.mp3 已完成：{final}")
    return final


def get_duration_seconds(mp3_path: Path) -> int:
    audio = MP3(mp3_path)
    return int(audio.info.length)
