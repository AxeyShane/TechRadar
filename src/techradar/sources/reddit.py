"""Reddit via the public read-only JSON API -- no auth needed for public
subreddits, just a real User-Agent (Reddit blocks generic/missing ones)."""

import logging

import httpx

log = logging.getLogger(__name__)

USER_AGENT = "TechRadar/0.1 (personal feed reader)"


async def fetch(
    subreddits: list[str], min_score: int = 50, max_items: int = 20, time_window: str = "day"
) -> list[dict]:
    items: list[dict] = []
    async with httpx.AsyncClient(timeout=15.0, headers={"User-Agent": USER_AGENT}) as client:
        for sub in subreddits:
            try:
                resp = await client.get(
                    f"https://www.reddit.com/r/{sub}/top.json",
                    params={"limit": max_items, "t": time_window},
                )
                resp.raise_for_status()
                posts = resp.json()["data"]["children"]
            except Exception as e:
                log.warning("Reddit r/%s failed: %s", sub, e)
                continue

            for post in posts:
                data = post.get("data", {})
                if data.get("stickied") or data.get("score", 0) < min_score:
                    continue
                url = data.get("url_overridden_by_dest") or f"https://reddit.com{data.get('permalink', '')}"
                items.append({
                    "source": f"r/{sub}",
                    "title": data.get("title", ""),
                    "url": url,
                    "summary": f"{data.get('score', 0)} upvotes, {data.get('num_comments', 0)} comments",
                    "published_at": None,
                })

    return items
