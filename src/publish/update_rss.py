"""維護 docs/feed.xml — Apple Podcasts / Spotify 共用 RSS feed。"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from feedgen.feed import FeedGenerator

from ..utils.config import DOCS_DIR, EPISODES_LOG, Settings
from ..utils.logger import logger

TAIPEI = ZoneInfo("Asia/Taipei")
FEED_PATH = DOCS_DIR / "feed.xml"


class EpisodeRecord:
    __slots__ = ("date", "title", "description", "audio_url", "duration_sec", "size_bytes")

    def __init__(
        self,
        *,
        date: str,
        title: str,
        description: str,
        audio_url: str,
        duration_sec: int,
        size_bytes: int,
    ) -> None:
        self.date = date
        self.title = title
        self.description = description
        self.audio_url = audio_url
        self.duration_sec = duration_sec
        self.size_bytes = size_bytes

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "title": self.title,
            "description": self.description,
            "audio_url": self.audio_url,
            "duration_sec": self.duration_sec,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EpisodeRecord":
        return cls(**d)


def load_episodes() -> list[EpisodeRecord]:
    if not EPISODES_LOG.exists():
        return []
    data = json.loads(EPISODES_LOG.read_text(encoding="utf-8"))
    return [EpisodeRecord.from_dict(d) for d in data]


def save_episodes(eps: list[EpisodeRecord]) -> None:
    EPISODES_LOG.parent.mkdir(parents=True, exist_ok=True)
    EPISODES_LOG.write_text(
        json.dumps([e.to_dict() for e in eps], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def append_episode(record: EpisodeRecord) -> list[EpisodeRecord]:
    """新增/取代同日集數，依日期排序回傳全清單。"""
    eps = load_episodes()
    eps = [e for e in eps if e.date != record.date]
    eps.append(record)
    eps.sort(key=lambda e: e.date)
    save_episodes(eps)
    return eps


def _format_duration(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def regenerate_feed(*, settings: Settings | None = None) -> Path:
    settings = settings or Settings.load(require_secrets=False)
    eps = load_episodes()

    fg = FeedGenerator()
    fg.load_extension("podcast")

    fg.title(settings.podcast_title)
    fg.author({"name": settings.podcast_author, "email": settings.podcast_email})
    fg.link(href=settings.podcast_homepage, rel="alternate")
    fg.link(href=settings.podcast_homepage + "/feed.xml", rel="self")
    fg.description(settings.podcast_description)
    fg.language(settings.podcast_language)
    fg.image(settings.podcast_cover_url)

    fg.podcast.itunes_author(settings.podcast_author)
    fg.podcast.itunes_summary(settings.podcast_description)
    fg.podcast.itunes_owner(name=settings.podcast_author, email=settings.podcast_email)
    fg.podcast.itunes_image(settings.podcast_cover_url)
    fg.podcast.itunes_category(settings.podcast_category, settings.podcast_subcategory)
    fg.podcast.itunes_explicit("yes" if settings.podcast_explicit else "no")
    fg.podcast.itunes_type("episodic")

    for ep in eps:
        fe = fg.add_entry()
        fe.id(ep.audio_url)
        fe.title(ep.title)
        fe.description(ep.description)
        fe.enclosure(ep.audio_url, str(ep.size_bytes), "audio/mpeg")
        fe.guid(ep.audio_url, permalink=False)
        fe.link(href=ep.audio_url)
        pub_dt = datetime.combine(
            date.fromisoformat(ep.date),
            datetime.min.time(),
            tzinfo=TAIPEI,
        ).replace(hour=18)  # 假設台北 18:00 發布
        fe.pubDate(pub_dt)
        fe.podcast.itunes_duration(_format_duration(ep.duration_sec))
        fe.podcast.itunes_explicit("yes" if settings.podcast_explicit else "no")
        # 每集獨立的封面圖（用節目同一張，Apple Podcasts Connect 才不會顯示「未提供」）
        fe.podcast.itunes_image(settings.podcast_cover_url)

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    fg.rss_file(str(FEED_PATH), pretty=True)
    logger.success(f"RSS feed 已更新：{FEED_PATH} (共 {len(eps)} 集)")
    return FEED_PATH


def regenerate_index_html(*, settings: Settings | None = None) -> Path:
    """產生簡易節目首頁，列出所有集數。"""
    settings = settings or Settings.load(require_secrets=False)
    eps = sorted(load_episodes(), key=lambda e: e.date, reverse=True)

    items_html = "\n".join(
        f"""    <li>
      <strong>{ep.date}</strong> — {ep.title}
      <br><small>{ep.description}</small>
      <br><audio controls src="{ep.audio_url}"></audio>
    </li>"""
        for ep in eps
    )
    html = f"""<!doctype html>
<html lang="zh-TW">
<head>
  <meta charset="utf-8">
  <title>{settings.podcast_title}</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body {{ font-family: -apple-system, "PingFang TC", "Microsoft JhengHei", sans-serif;
            max-width: 720px; margin: 2rem auto; padding: 0 1rem; line-height: 1.6; }}
    li {{ margin-bottom: 1.5rem; }}
    audio {{ width: 100%; margin-top: .5rem; }}
    .feeds a {{ display: inline-block; margin-right: 1rem; }}
  </style>
</head>
<body>
  <h1>{settings.podcast_title}</h1>
  <p>{settings.podcast_description}</p>
  <p class="feeds">
    <a href="./feed.xml">RSS Feed</a>
    <a href="https://podcasts.apple.com/">Apple Podcasts</a>
    <a href="https://open.spotify.com/">Spotify</a>
  </p>
  <h2>集數列表</h2>
  <ul>
{items_html}
  </ul>
</body>
</html>
"""
    path = DOCS_DIR / "index.html"
    path.write_text(html, encoding="utf-8")
    return path
