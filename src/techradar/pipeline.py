"""Fetch all enabled sources, dedupe against the DB, score, store."""

import asyncio
import logging
from datetime import datetime, timezone

from techradar import database
from techradar.config import load_interests, load_sources
from techradar.scorer import score_item
from techradar.sources import feeds, github_trending, hackernews, reddit

log = logging.getLogger(__name__)


async def fetch_all(sources_cfg: dict) -> list[dict]:
    tasks = []

    hn_cfg = sources_cfg.get("hackernews", {})
    if hn_cfg.get("enabled"):
        tasks.append(hackernews.fetch(
            min_score=hn_cfg.get("min_score", 80),
            max_items=hn_cfg.get("max_items", 60),
        ))

    gh_cfg = sources_cfg.get("github_trending", {})
    if gh_cfg.get("enabled"):
        tasks.append(github_trending.fetch(
            since=gh_cfg.get("since", "daily"),
            languages=gh_cfg.get("languages", [""]),
        ))

    reddit_cfg = sources_cfg.get("reddit", {})
    if reddit_cfg.get("enabled"):
        tasks.append(reddit.fetch(
            subreddits=reddit_cfg.get("subreddits", []),
            min_score=reddit_cfg.get("min_score", 50),
            max_items=reddit_cfg.get("max_items", 20),
            time_window=reddit_cfg.get("time_window", "day"),
        ))

    arxiv_cfg = sources_cfg.get("arxiv", {})
    if arxiv_cfg.get("enabled"):
        tasks.append(feeds.fetch_arxiv(
            categories=arxiv_cfg.get("categories", []),
            max_items=arxiv_cfg.get("max_items", 30),
        ))

    blog_feeds = sources_cfg.get("feeds") or []
    if blog_feeds:
        tasks.append(feeds.fetch_blogs(blog_feeds))

    # Optional proactive discovery sweeps (TOAST-1 / LLM) run in-process
    # before the async gather (they drive their own sequential tool loop).
    discovery_items: list[dict] = []
    disc_cfg = sources_cfg.get("discovery") or {}
    if disc_cfg.get("enabled"):
        from techradar.sources import discovery
        log.info("Running discovery sweeps...")
        discovery_items = discovery.sweep(
            topics=disc_cfg.get("topics"),
            days=int(disc_cfg.get("days", 7)),
            provider=disc_cfg.get("provider"),
            max_items=int(disc_cfg.get("max_items", 10)),
        )
        log.info("Discovery sweeps returned %d candidate(s)", len(discovery_items))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    items: list[dict] = []
    for r in results:
        if isinstance(r, Exception):
            log.error("Source fetch failed: %s", r)
            continue
        items.extend(r)
    items.extend(discovery_items)

    return items


def dedupe_new(conn, raw_items: list[dict], limit_new: int | None = None) -> list[dict]:
    """Drop items already in the DB or repeated within this batch."""
    new_items = []
    seen_urls: set[str] = set()
    for item in raw_items:
        url = item.get("url")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        if database.item_exists(conn, url):
            continue
        new_items.append(item)
    return new_items[:limit_new] if limit_new else new_items


def score_and_store(conn, new_items: list[dict], profile: str) -> int:
    """Enrich (YouTube transcript summary if applicable), score, store.
    Shared by the live fetch pipeline and the channel backfill command so
    both apply identical scoring/enrichment. Returns count scored."""
    notes = database.get_approved_notes(conn)
    watched = database.get_watched_titles(conn, limit=15)
    now = datetime.now(timezone.utc).isoformat()
    scored = 0
    for item in new_items:
        if feeds.youtube_video_id(item.get("url", "")):
            yt_summary = feeds.fetch_youtube_summary(item["url"])
            if yt_summary:
                item["summary"] = yt_summary
        score, reason = score_item(item, profile, notes=notes, watched=watched)
        item["fit_score"] = score
        item["reason"] = reason
        item["discovered_at"] = now
        database.store_item(conn, item)
        scored += 1
        log.info("[%d/10] %s | %s", score, item["source"], item["title"][:70])
    return scored


def run(limit_new: int | None = None) -> dict:
    """Fetch, dedupe, score, store. Returns stats."""
    sources_cfg = load_sources()
    interests_cfg = load_interests()
    profile = interests_cfg.get("profile", "")

    conn = database.get_connection()

    log.info("Fetching sources...")
    raw_items = asyncio.run(fetch_all(sources_cfg))
    log.info("Fetched %d raw items", len(raw_items))

    new_items = dedupe_new(conn, raw_items, limit_new)
    log.info("%d new items to score", len(new_items))

    scored = score_and_store(conn, new_items, profile)

    conn.close()
    return {"fetched": len(raw_items), "new": len(new_items), "scored": scored}
