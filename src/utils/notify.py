"""Discord webhook 通知（成功/失敗）。"""
from __future__ import annotations

import httpx

from .config import Settings
from .logger import logger


def send_discord(content: str, *, settings: Settings | None = None) -> None:
    settings = settings or Settings.load(require_secrets=False)
    if not settings.discord_webhook:
        logger.debug("未設定 DISCORD_WEBHOOK，略過通知")
        return
    try:
        resp = httpx.post(
            settings.discord_webhook,
            json={"content": content[:1900]},
            timeout=10.0,
        )
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - 通知失敗不影響主流程
        logger.warning(f"Discord 通知失敗: {exc}")
