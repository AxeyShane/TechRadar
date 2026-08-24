"""Patent watch -- surface newly-published patents in your domains, AHEAD of
the YouTube/blog explainer videos.

Objective ("ahead of T3CH"): the day a relevant patent is published, drop it
into TechRadar as a scored item with a grounded "why", before anyone has made
a video about it.

Why reliable: patent-news coverage (like the Bambu case) is picked up by the
web the same day it publishes, days before the `ThemExplainers`/T3CH videos.
So the dependable pipeline is:
    OpenRouter LLM (your LLM_URL/....) plans targeted searches ->
    reliable keyless web search (DuckDuckGo lite) finds the fresh coverage ->
    the LLM curates the recently-published, profile-relevant filings ->
    score_and_store puts them in the feed like every other item.

Optional authoritative cross-check: Google Patents (US/EP/WIPO/CN index) can
verify gate-keeping, but it aggressively rate-limits (IP 503s under bursts),
so it runs at LOW frequency and only if patents.google_patents is true.
"""

import datetime
import json
import logging
import re

from techradar.config import load_interests
from techradar.llm import get_client
from techradar.scorer import _extract_json
from techradar.sources.discovery import search_web

log = logging.getLogger(__name__)

PLAN_PROMPT = """You run a patent radar for ONE reader's technology feed.
READER'S PROFILE:
{profile}

Domains / assignees to watch:
{domains}

Goal: find patents just published (within the last {days} days) in THESE
domains/assignees that this reader would want to know FIRST. The domains are
the subject -- your queries must center on them, NOT on the general profile.
Generate exactly one focused query per domain/assignee listed, using its exact
name/topic, and only then use spare budget for closely-related terms. Include
"patent", "filed", or "new" plus a recency hint (recent / this month) so the
search returns freshly-published patent news, not evergreen content. For a
named company (e.g. Bambu Lab) use "<company> new patent".

Return ONLY valid JSON: {{"queries": ["...", "..."]}}"""

CURATE_PROMPT = """You curate web results into a patent radar for ONE reader.
READER'S PROFILE:
{profile}

Sweep window: last {days} days.

Web search results:
{results}

From these, pick up to {max_items} results that are about RECENTLY PUBLISHED
patents in the reader's domains. REQUIRE the item specifically describes a
newly-published/filed patent (ideally naming the assignee or a patent/application),
within the {days}-day window. EXCLUDE company homepages, patent *lawsuits*,
generic industry pieces with no specific filing, and old content. Drop
duplicates (same filing covered by many sites -- keep the most substantive).

Return ONLY valid JSON: {{"items": [{{"url": "...", "title": "...",
"why": "<under 20 words, why this patent matters to THIS reader>"}}]}}"""


def _llm_plan(profile: str, domains: list[str], days: int, n_queries: int) -> list[str]:
    raw = get_client().ask(
        PLAN_PROMPT.format(profile=profile or "(not provided)",
                           domains="\n".join(f"- {d}" for d in domains),
                           days=days, n_queries=n_queries),
        temperature=0.3, max_tokens=600,
    )
    data = _extract_json(raw)
    return [str(q) for q in data.get("queries", []) if str(q).strip()][:n_queries]


def _llm_curate(profile: str, days: int, results: list[dict], max_items: int) -> list[dict]:
    if not results:
        return []
    block = "\n".join(f"- [{r['title']}] {r['url']}\n  {r.get('snippet','')[:220]}" for r in results)
    raw = get_client().ask(
        CURATE_PROMPT.format(profile=profile or "(not provided)", days=days,
                             max_items=max_items, results=block),
        temperature=0.2, max_tokens=1500,
    )
    data = _extract_json(raw)
    items = []
    for it in data.get("items", []):
        url = str(it.get("url", "")).strip()
        if not url.startswith("http"):
            continue
        title = str(it.get("title", "")).strip() or url
        items.append({
            "url": url,
            "title": title,
            "source": "patents",
            "summary": str(it.get("why", "")),
            "published_at": datetime.date.today().isoformat(),
        })
    return items


def _google_patents_keywords(domains: list[str], days: int, max_items: int) -> list[dict]:
    """Optional authoritative cross-check. Deliberately LOW-frequency: one
    small query per keyword, and it is best-effort -- Google throttles hard."""
    import time
    from techradar.patents_tools import search_google_patents  # local import to keep import-light
    today = datetime.date.today()
    cutoff = (today - datetime.timedelta(days=days)).isoformat()
    out: list[dict] = []
    seen: set[str] = set()
    for kw in domains:
        for p in search_google_patents(kw, 10):
            d = (p.get("publication_date") or "")[:10]
            if not d or d < cutoff or d > today.isoformat():
                continue
            k = p.get("publication_number") or p.get("url")
            if not k or k in seen:
                continue
            seen.add(k)
            out.append({
                "url": p.get("url", ""),
                "title": p.get("title") or "(patent)",
                "source": "patents",
                "summary": f"{p.get('assignee','')} -- {p.get('snippet','')[:160]}",
                "published_at": d,
            })
            if len(out) >= max_items:
                return out
        time.sleep(2)
    return out


def run(domains: list[str] | None = None, days: int = 30, max_items: int = 10,
        dry_run: bool = False, n_queries: int = 6) -> list[dict]:
    """Watch newly-published patents across the given domains/assignees and
    return scored-ready items (empty on any failure)."""
    from techradar.config import load_sources

    cfg = load_sources().get("patents") or {}
    if not domains:
        domains = [str(k) for k in cfg.get("keywords", []) if str(k).strip()]
    if not domains:
        log.warning("No patent watch domains/keywords configured (config/sources.yaml -> patents.keywords)")
        return []

    profile = load_interests().get("profile", "") or ""
    n_queries = n_queries or 6
    if dry_run:
        log.info("[dry-run] patent radar would watch %d domain(s): %s", len(domains), domains)
        return []

    # 1) plan queries (LLM)
    queries = _llm_plan(profile, domains, days, n_queries)
    # 2) reliable web search
    results: list[dict] = []
    seen: set[str] = set()
    for q in queries:
        try:
            for r in search_web(q):
                if r["url"] not in seen:
                    seen.add(r["url"]); results.append(r)
        except Exception as e:
            log.warning("patent web search failed (%s): %s", q, e)
    # 3) curate
    items = _llm_curate(profile, days, results, max_items)

    # 4) optional authoritative cross-check (low frequency)
    if str(cfg.get("google_patents", False)).lower() in ("1", "true", "yes"):
        try:
            items += _google_patents_keywords(domains, days, max_items)
        except Exception as e:
            log.warning("Google Patents cross-check failed: %s", e)
    return items[:max_items]
