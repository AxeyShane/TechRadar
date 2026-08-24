"""Analyze an explicitly-shared URL so it can join the ranked feed.

Used by the share-to-TechRadar flow: the user (often from a phone share sheet)
drops a link in; we turn it into a scored, summarized item the same way the
pipeline treats feed items, so the dashboard can show the user *why* TechRadar
thinks it matters to them -- the same "reason" commitment as every other item.

Strategy per URL kind:
  - YouTube:      try official captions (existing feeds.fetch_youtube_summary);
                  if unavailable (or IP-blocked), fall back to LOCAL
                  transcription (faster-whisper via transcriber.py).
  - Other page:   extract readable text with crawl4ai (already a dependency),
                  then chunked map-reduce summarize with the LLM client
                  (OpenRouter by default).
Always best-effort: on any failure we still store the item (title-only) so the
inbox keeps the share and the user can see it failed to analyze.
"""

import asyncio
import logging
import re

from techradar.config import load_interests
from techradar.database import get_approved_notes, get_connection
from techradar.scorer import score_item
from techradar.summarizer import summarize_text

log = logging.getLogger(__name__)

PAGE_TEXT_CHARS = 60000          # cap before summarization
TITLE_CHARS = 300


def _crawl4ai_extract(url: str) -> tuple[str | None, str | None]:
    """Returns (text, title) via headless crawl4ai; None on failure."""
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    except ImportError:
        log.warning("crawl4ai unavailable for %s", url)
        return None, None

    async def _run():
        cfg = CrawlerRunConfig(stream=False, verbose=False)
        async with AsyncWebCrawler(config=BrowserConfig(headless=True)) as crawler:
            result = await crawler.arun(url=url, config=cfg)
            if not result or result.status_code and result.status_code >= 400:
                return None, None
            text = result.markdown or result.html or ""
            return text, (result.metadata.get("title") if result.metadata else None)

    try:
        return asyncio.run(_run())
    except Exception as e:
        log.warning("crawl4ai extraction failed for %s: %s", url, e)
        return None, None


def analyze_url(url: str, title_hint: str = "") -> dict:
    """Analyze a URL and return an enriched, scored item dict.
    Non-fatal: always returns a dict; on failure score stays None and
    summary may be empty (caller still stores it)."""
    from techradar import transcriber
    from techradar.sources.feeds import fetch_youtube_summary, youtube_video_id

    profile = load_interests().get("profile", "")
    conn = get_connection()
    try:
        notes = get_approved_notes(conn)
    finally:
        conn.close()

    item = {"url": url, "source": "shared", "title": title_hint.strip() or url, "summary": ""}

    if youtube_video_id(url):
        # Captions path first, then local ASR fallback (graceful).
        yt_summary = fetch_youtube_summary(url)
        if yt_summary:
            item["summary"] = yt_summary
            item["title"] = title_hint.strip() or item["title"]
        else:
            local = transcriber.transcribe_and_summarize(url)
            if local:
                item["summary"] = local
    else:
        text, found_title = _crawl4ai_extract(url)
        if found_title:
            item["title"] = found_title[:TITLE_CHARS]
        if text:
            plain = re.sub(r"\s+", " ", text).strip()[:PAGE_TEXT_CHARS]
            item["summary"] = summarize_text(plain, title=item["title"])

    if item["summary"]:
        score, reason = score_item(item, profile, notes=notes)
        item["fit_score"] = score
        item["reason"] = reason
    else:
        item["fit_score"] = None
        item["reason"] = "couldn't analyze this page (no transcript/text or LLM unavailable)"
    return item
