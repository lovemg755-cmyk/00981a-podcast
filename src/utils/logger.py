"""Loguru 包裝：依環境決定輸出格式。"""
from __future__ import annotations

import os
import sys

from loguru import logger as _logger

_logger.remove()

_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> "
    "| <level>{level: <8}</level> "
    "| <cyan>{name}:{function}:{line}</cyan> - <level>{message}</level>"
)

_logger.add(
    sys.stderr,
    format=_FORMAT,
    level=os.getenv("LOG_LEVEL", "INFO"),
    colorize=True,
)

logger = _logger
