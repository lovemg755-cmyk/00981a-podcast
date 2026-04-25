"""集中載入環境變數與常數。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# 注入 OS 憑證庫（Python 3.13+ Windows 對部分台灣網站憑證更嚴格，需走系統 CA）
try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

# 把 static-ffmpeg 帶入的 ffmpeg/ffprobe 加到 PATH（Windows 用戶免裝系統 ffmpeg）
try:
    import static_ffmpeg

    static_ffmpeg.add_paths()
except ImportError:
    pass

from dotenv import load_dotenv

# 載入 .env：本地以 .env 為主（override=True），但 CI 透過旗標關閉以避免覆蓋 GitHub Secrets
load_dotenv(override=os.getenv("DOTENV_OVERRIDE", "true").lower() == "true")

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
HOLDINGS_DIR = DATA_DIR / "holdings"
EPISODES_LOG = DATA_DIR / "episodes.json"
DOCS_DIR = PROJECT_ROOT / "docs"
ASSETS_DIR = PROJECT_ROOT / "assets"
BUILD_DIR = PROJECT_ROOT / "build"


def _env(key: str, default: str | None = None, required: bool = False) -> str:
    val = os.getenv(key, default)
    if required and not val:
        raise RuntimeError(f"必要環境變數 {key} 未設定")
    return val or ""


@dataclass(frozen=True)
class Settings:
    # Claude
    anthropic_api_key: str
    claude_script_model: str
    claude_filter_model: str

    # Cloudflare R2
    r2_access_key: str
    r2_secret_key: str
    r2_bucket: str
    r2_endpoint: str
    r2_public_url: str

    # Podcast 元資料
    podcast_title: str
    podcast_author: str
    podcast_email: str
    podcast_description: str
    podcast_language: str
    podcast_category: str
    podcast_subcategory: str
    podcast_explicit: bool
    podcast_homepage: str
    podcast_cover_url: str

    # TTS
    tts_voice: str
    tts_rate: str
    tts_pitch: str

    # 通知
    discord_webhook: str

    # 旗標
    dry_run: bool

    @classmethod
    def load(cls, *, require_secrets: bool = True) -> "Settings":
        return cls(
            anthropic_api_key=_env("ANTHROPIC_API_KEY", required=require_secrets),
            claude_script_model=_env("CLAUDE_SCRIPT_MODEL", "claude-sonnet-4-6"),
            claude_filter_model=_env("CLAUDE_FILTER_MODEL", "claude-haiku-4-5-20251001"),
            r2_access_key=_env("R2_ACCESS_KEY", required=require_secrets),
            r2_secret_key=_env("R2_SECRET_KEY", required=require_secrets),
            r2_bucket=_env("R2_BUCKET", required=require_secrets),
            r2_endpoint=_env("R2_ENDPOINT", required=require_secrets),
            r2_public_url=_env("R2_PUBLIC_URL", required=require_secrets),
            podcast_title=_env("PODCAST_TITLE", "00981A 每日持股觀察"),
            podcast_author=_env("PODCAST_AUTHOR", "AI 主播"),
            podcast_email=_env("PODCAST_EMAIL", "noreply@example.com"),
            podcast_description=_env(
                "PODCAST_DESCRIPTION",
                "每個交易日追蹤 00981A 持股變化、投資策略與催化劑。",
            ),
            podcast_language=_env("PODCAST_LANGUAGE", "zh-TW"),
            podcast_category=_env("PODCAST_CATEGORY", "Business"),
            podcast_subcategory=_env("PODCAST_SUBCATEGORY", "Investing"),
            podcast_explicit=_env("PODCAST_EXPLICIT", "false").lower() == "true",
            podcast_homepage=_env("PODCAST_HOMEPAGE", "https://example.com"),
            podcast_cover_url=_env("PODCAST_COVER_URL", "https://example.com/cover.png"),
            tts_voice=_env("TTS_VOICE", "zh-TW-HsiaoChenNeural"),
            tts_rate=_env("TTS_RATE", "+0%"),
            tts_pitch=_env("TTS_PITCH", "+0Hz"),
            discord_webhook=_env("DISCORD_WEBHOOK", ""),
            dry_run=_env("DRY_RUN", "false").lower() == "true",
        )
