"""上傳 mp3 到 Cloudflare R2 (S3 相容)。"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import boto3
from botocore.config import Config

from ..utils.config import Settings
from ..utils.logger import logger


def _client(settings: Settings):
    return boto3.client(
        service_name="s3",
        endpoint_url=settings.r2_endpoint,
        aws_access_key_id=settings.r2_access_key,
        aws_secret_access_key=settings.r2_secret_key,
        config=Config(signature_version="s3v4", region_name="auto"),
    )


def episode_object_key(pub_date: date) -> str:
    return f"episodes/{pub_date.year}/{pub_date.month:02d}/{pub_date.isoformat()}.mp3"


def upload_episode(mp3_path: Path, pub_date: date, *, settings: Settings) -> str:
    """回傳該集 mp3 的公開 URL。"""
    key = episode_object_key(pub_date)
    client = _client(settings)
    logger.info(f"上傳 {mp3_path.name} → r2://{settings.r2_bucket}/{key}")
    client.upload_file(
        Filename=str(mp3_path),
        Bucket=settings.r2_bucket,
        Key=key,
        ExtraArgs={
            "ContentType": "audio/mpeg",
            "CacheControl": "public, max-age=31536000",
        },
    )
    public_url = f"{settings.r2_public_url.rstrip('/')}/{key}"
    logger.success(f"上傳完成：{public_url}")
    return public_url
