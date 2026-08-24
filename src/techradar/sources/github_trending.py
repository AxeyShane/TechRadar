"""GitHub Trending has no API -- scrape it with Crawl4AI's structured CSS
extraction (schema + selectors, no LLM call needed; page structure is stable)."""

import logging

from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

log = logging.getLogger(__name__)

SCHEMA = {
    "name": "GitHub Trending",
    "baseSelector": "article.Box-row",
    "fields": [
        {"name": "path", "selector": "h2 a", "type": "attribute", "attribute": "href"},
        {"name": "title", "selector": "h2 a", "type": "text"},
        {"name": "description", "selector": "p.col-9", "type": "text"},
        {"name": "language", "selector": "[itemprop=programmingLanguage]", "type": "text"},
        {"name": "stars", "selector": "a[href$='/stargazers']", "type": "text"},
    ],
}


async def fetch(since: str = "daily", languages: list[str] | None = None) -> list[dict]:
    languages = languages or [""]
    run_config = CrawlerRunConfig(extraction_strategy=JsonCssExtractionStrategy(SCHEMA))

    items: list[dict] = []
    async with AsyncWebCrawler() as crawler:
        for lang in languages:
            url = f"https://github.com/trending/{lang}?since={since}"
            try:
                result = await crawler.arun(url=url, config=run_config)
            except Exception as e:
                log.warning("GitHub Trending (%s) failed: %s", lang or "all", e)
                continue

            if not result.success or not result.extracted_content:
                continue

            import json
            repos = json.loads(result.extracted_content)
            for repo in repos:
                path = (repo.get("path") or "").strip()
                if not path:
                    continue
                title = " ".join((repo.get("title") or "").split())
                items.append({
                    "source": "GitHub Trending",
                    "title": title or path.strip("/"),
                    "url": f"https://github.com{path}",
                    "summary": f"{(repo.get('description') or '').strip()} "
                               f"[{(repo.get('language') or '?').strip()}, "
                               f"{(repo.get('stars') or '?').strip()} stars]".strip(),
                    "published_at": None,
                })

    return items
