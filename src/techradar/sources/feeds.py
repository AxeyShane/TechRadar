"""ArXiv (official Atom API) and user-configured blog/YouTube RSS feeds.
Both are Atom/RSS, so feedparser handles either without custom XML code."""

import asyncio
import logging
import re

import feedparser
import httpx

log = logging.getLogger(__name__)

ARXIV_API = "https://export.arxiv.org/api/query"
YOUTUBE_URL_RE = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})")


def youtube_video_id(url: str) -> str | None:
    match = YOUTUBE_URL_RE.search(url or "")
    return match.group(1) if match else None


def fetch_youtube_summary(url: str) -> str | None:
    """Transcript -> short LLM summary, so scoring judges the actual video
    content instead of the channel's boilerplate RSS description. Returns
    None (caller keeps the RSS summary) if no captions or the LLM call fails."""
    video_id = youtube_video_id(url)
    if not video_id:
        return None
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        transcript = YouTubeTranscriptApi().fetch(video_id)
        text = " ".join(snippet.text for snippet in transcript)[:8000]
    except Exception as e:
        log.warning("Transcript fetch failed for %s: %s", url, e)
        return None

    from techradar.llm import get_client
    try:
        summary = get_client().ask(
            "Summarize this YouTube video transcript in 2-3 sentences, "
            f"focused on what's concretely new or useful:\n\n{text}",
            temperature=0.0, max_tokens=200,
        )
        return summary.strip()
    except Exception as e:
        log.warning("Transcript summarization failed for %s: %s", url, e)
        return None


async def fetch_arxiv(categories: list[str], max_items: int = 30) -> list[dict]:
    if not categories:
        return []
    search_query = " OR ".join(f"cat:{c}" for c in categories)
    params = {
        "search_query": search_query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": max_items,
    }
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(ARXIV_API, params=params)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.text)

    items: list[dict] = []
    for entry in parsed.entries:
        items.append({
            "source": "ArXiv",
            "title": " ".join(entry.get("title", "").split()),
            "url": entry.get("link", ""),
            "summary": " ".join(entry.get("summary", "")[:400].split()),
            "published_at": entry.get("published"),
        })
    return items


async def _fetch_one_feed(client: httpx.AsyncClient, feed_cfg: dict) -> list[dict]:
    name = feed_cfg.get("name", "?")
    url = feed_cfg.get("url", "")
    if not url:
        return []
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        parsed = feedparser.parse(resp.content)
    except Exception as e:
        log.warning("Feed %s failed: %s", name, e)
        return []

    return [
        {
            "source": name,
            "title": entry.get("title", ""),
            "url": entry.get("link", ""),
            "summary": " ".join(entry.get("summary", "")[:400].split()) if entry.get("summary") else "",
            "published_at": entry.get("published"),
        }
        for entry in parsed.entries[:15]
    ]


async def fetch_blogs(feeds: list[dict], concurrency: int = 15) -> list[dict]:
    """feeds: [{"name": ..., "url": ...}, ...] from config/sources.yaml.
    Fetched concurrently (capped -- YouTube and co. will rate-limit/block a
    single IP hammering hundreds of feeds at once) instead of one at a time."""
    sem = asyncio.Semaphore(concurrency)

    async def bound_fetch(client: httpx.AsyncClient, feed_cfg: dict) -> list[dict]:
        async with sem:
            return await _fetch_one_feed(client, feed_cfg)

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        results = await asyncio.gather(*(bound_fetch(client, f) for f in feeds))

    items: list[dict] = []
    for r in results:
        items.extend(r)
    return items
