"""Hacker News via the official Firebase API -- no scraping needed."""

import logging

import httpx

log = logging.getLogger(__name__)

API = "https://hacker-news.firebaseio.com/v0"


async def fetch(min_score: int = 80, max_items: int = 60) -> list[dict]:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{API}/topstories.json")
        ids = resp.json()[:max_items * 2]  # over-fetch, filter by score below

        items: list[dict] = []
        for story_id in ids:
            if len(items) >= max_items:
                break
            try:
                r = await client.get(f"{API}/item/{story_id}.json")
                story = r.json()
            except Exception as e:
                log.warning("HN item %s failed: %s", story_id, e)
                continue

            if not story or story.get("score", 0) < min_score:
                continue
            if story.get("type") != "story":
                continue

            items.append({
                "source": "Hacker News",
                "title": story.get("title", ""),
                "url": story.get("url") or f"https://news.ycombinator.com/item?id={story_id}",
                "summary": f"{story.get('score', 0)} points, {story.get('descendants', 0)} comments",
                "published_at": None,
            })

        return items
