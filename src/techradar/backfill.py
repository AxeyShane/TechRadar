"""Backfill a YouTube channel's full video history -- the live RSS feed only
ever holds the last ~15 uploads, so a channel you're newly following needs a
one-time catch-up pass instead of waiting for new uploads."""

import logging
import re

from techradar import database
from techradar.config import load_interests, load_sources
from techradar.pipeline import dedupe_new, score_and_store

log = logging.getLogger(__name__)

CHANNEL_ID_RE = re.compile(r"channel_id=([\w-]+)")


def _resolve_channel_url(channel: str) -> str:
    """channel: a feed name from sources.yaml, a channel_id, a @handle, or
    a full URL -- resolve to a /videos URL yt-dlp can list."""
    sources_cfg = load_sources()
    for feed in sources_cfg.get("feeds") or []:
        if feed.get("name", "").lower() == channel.lower():
            match = CHANNEL_ID_RE.search(feed.get("url", ""))
            if match:
                return f"https://www.youtube.com/channel/{match.group(1)}/videos"

    if channel.startswith("http"):
        return channel if channel.rstrip("/").endswith("videos") else channel.rstrip("/") + "/videos"
    if channel.startswith("UC"):
        return f"https://www.youtube.com/channel/{channel}/videos"
    handle = channel if channel.startswith("@") else f"@{channel}"
    return f"https://www.youtube.com/{handle}/videos"


def list_channel_videos(channel: str) -> list[dict]:
    """Flat listing (fast -- no per-video fetch), title + URL only. No
    upload dates: YouTube's flat channel listing doesn't expose them without
    a much slower per-video fetch."""
    from yt_dlp import YoutubeDL

    url = _resolve_channel_url(channel)
    opts = {"extract_flat": "in_playlist", "quiet": True, "skip_download": True}
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries = info.get("entries") or []
    items = []
    for e in entries:
        video_id = e.get("id")
        if not video_id:
            continue
        items.append({
            "source": info.get("channel") or info.get("uploader") or channel,
            "title": e.get("title", ""),
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "summary": "",
            "published_at": None,
        })
    return items


def run(channel: str, limit: int | None = None) -> dict:
    """List, dedupe against the DB, score, store. Returns stats."""
    profile = load_interests().get("profile", "")
    conn = database.get_connection()

    log.info("Listing videos for %s...", channel)
    raw_items = list_channel_videos(channel)
    log.info("Found %d videos", len(raw_items))

    new_items = dedupe_new(conn, raw_items, limit)
    log.info("%d new videos to score", len(new_items))

    scored = score_and_store(conn, new_items, profile)

    conn.close()
    return {"found": len(raw_items), "new": len(new_items), "scored": scored}
