"""Proactive discovery sweeps: the "front row beyond your feeds" source + the
TOAST-1 deep-search integration.

A sweep goes OUT and looks: given a topic + the owner's interest profile, it
plans search queries, runs them across the web, and curates the most notable
results into candidate items, which flow through the normal score_and_store
pipeline.

Two providers (both call an LLM to PLAN and CURATE, and run the same reliable
lite web search in between -- the difference is WHICH model reasons):

  provider: llm         (default) -- uses the existing LLM client (OpenRouter
                        or local llama.cpp via LLM_URL/...). Works today.
  provider: mixedbread  -- uses Mixedbread's TOAST-1 search agent model
                        (model "toast-1") through its OpenAI-compatible
                        Completions API for planning + curation. Needs
                        MIXEDBREAD_API_KEY.

NOTE on TOAST-1: its hosted self-build function-calling harness is unreliable
today (the server 500s on custom web_search/tool schemas), but toast-1 works
cleanly as a plain reasoning model. So we use toast-1 to plan queries and
curate evidence, and our own keyless DuckDuckGo-lite search to actually run the
searches. That keeps the AGENT heavy-lifting on TOAST-1 while the tool loop
stays robust on our side.
"""

import json
import logging
import os
import urllib.parse

import httpx

from techradar.llm import get_client
from techradar.scorer import _extract_json

log = logging.getLogger(__name__)

MB_BASE_URL = "https://api.mixedbread.com/v1"
MB_MODEL = "toast-1"
SNIPPET_CHARS = 500

PLAN_PROMPT = """You are a research planner for a personal technology feed.
READER'S PROFILE:
{profile}

Sweep topic: {topic}
Look for: NEW and NOTABLE developments within the last {days} days --
projects, papers, tools, announcements, videos, or products that this reader
would genuinely want to know about first.

Produce {n_queries} diverse, high-precision web-search queries (natural-language
questions or keyword phrases) that together would surface the best candidates.

Return ONLY valid JSON: {{"queries": ["...", "..."]}}"""

CURATE_PROMPT = """You curate web search results into a personal tech feed.
READER'S PROFILE:
{profile}

Sweep topic: {topic}
Search results to curate:
{results}

Pick up to {max_items} items that are genuinely notable AND NEW (past ~{days}
days). Prefer concrete, substantive work (projects, papers, tools, videos,
announcements) over hype, generic news, or paywalled link-bait. Skip
duplicates and anything the reader's stated low-interest areas cover.

Return ONLY valid JSON: {{"items": [{{"url": "...", "title": "...",
"why": "<under 20 words, why this matters to THIS reader>"}}]}}"""


# ---------------------------------------------------------------------------
# Search backend (keyless, reliable)
# ---------------------------------------------------------------------------

def search_web(query: str, max_results: int = 8) -> list[dict]:
    """Keyless DuckDuckGo *lite* search (html.duckduckgo.com returns 202
    challenge pages; lite is scrape-friendly). Returns [{url,title,snippet}]."""
    resp = httpx.get("https://lite.duckduckgo.com/lite/", params={"q": query},
                     timeout=20.0,
                     headers={"User-Agent": "Mozilla/5.0 (TechRadar personal feed)"})
    resp.raise_for_status()
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for a in soup.select("a.result-link")[:max_results]:
        title = a.get_text(" ", strip=True) or ""
        real = _clean_ddg_url(a.get("href", ""))
        snippet = ""
        row = a.find_parent("tr")
        if row is not None:
            td = row.find("td", class_="result-snippet") or row.find("td")
            if td is not None:
                snippet = td.get_text(" ", strip=True)[:SNIPPET_CHARS]
        if real.startswith("http") and real not in {r["url"] for r in results}:
            results.append({"url": real, "title": title, "snippet": snippet})
    return results


def _clean_ddg_url(href: str) -> str:
    if not href.startswith("http"):
        parsed = urllib.parse.urlparse(href)
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs:
            return qs["uddg"][0]
    return href


# ---------------------------------------------------------------------------
# LLM ask callables (planner/curator backends)
# ---------------------------------------------------------------------------

def _ask_llm(prompt: str, temperature: float = 0.2, max_tokens: int = 1200) -> str:
    return get_client().ask(prompt, temperature=temperature, max_tokens=max_tokens).strip()


def _ask_mixedbread(prompt: str, temperature: float = 0.2, max_tokens: int = 1200) -> str:
    key = os.environ.get("MIXEDBREAD_API_KEY", "").strip()
    if not key:
        raise ValueError(
            "provider=mixedbread needs MIXEDBREAD_API_KEY in ~/.techradar/.env "
            "(model toast-1 via api.mixedbread.com). Use provider=llm to run "
            "sweeps with the existing LLM client instead."
        )
    base = os.environ.get("MIXEDBREAD_BASE_URL", MB_BASE_URL).rstrip("/")
    resp = httpx.post(
        f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": MB_MODEL, "messages": [{"role": "user", "content": prompt}],
              "temperature": temperature, "max_tokens": max_tokens},
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# Plan / curate (shared by both providers)
# ---------------------------------------------------------------------------

def _plan(ask, topic: str, profile: str, days: int, n_queries: int) -> list[str]:
    raw = ask(PLAN_PROMPT.format(profile=profile or "(not provided)", topic=topic,
                                 days=days, n_queries=n_queries), 0.3, 600)
    data = _extract_json(raw)
    return [str(q) for q in data.get("queries", []) if str(q).strip()][:n_queries]


def _curate(ask, topic: str, profile: str, days: int, results: list[dict], max_items: int) -> list[dict]:
    if not results:
        return []
    block = "\n".join(
        f"- [{r['title']}] {r['url']}\n  {r['snippet'][:300]}"
        for r in results
    )
    raw = ask(CURATE_PROMPT.format(profile=profile or "(not provided)", topic=topic,
                                   days=days, results=block, max_items=max_items),
              0.2, 1500)
    data = _extract_json(raw)
    items = []
    for it in data.get("items", []):
        url = str(it.get("url", "")).strip()
        title = str(it.get("title", "")).strip() or url
        if url.startswith("http"):
            items.append({"url": url, "title": title, "source": f"discovery:{topic}",
                          "summary": str(it.get("why", ""))})
    return items


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def sweep(topics: list[str] | None = None, days: int = 7, provider: str | None = None,
          max_items: int = 10, dry_run: bool = False) -> list[dict]:
    from techradar.config import load_interests, load_sources

    cfg = load_sources().get("discovery") or {}
    if not topics:
        topics = [str(t) for t in cfg.get("topics", []) if str(t).strip()]
    if not topics:
        log.warning("No discovery topics configured (config/sources.yaml -> discovery.topics)")
        return []
    if not provider:
        provider = str(os.environ.get("DISCOVERY_PROVIDER", cfg.get("provider", "llm"))).lower()

    ask = _ask_mixedbread if provider == "mixedbread" else _ask_llm
    profile = load_interests().get("profile", "") or ""
    per_topic = max(max_items // max(1, len(topics)), 2)
    all_items: list[dict] = []
    for topic in topics:
        try:
            if dry_run:
                log.info("[dry-run] provider=%s topic=%r", provider, topic)
                continue
            queries = _plan(ask, topic, profile, days, 5)
            results: list[dict] = []
            seen: set[str] = set()
            for q in queries:
                try:
                    for r in search_web(q):
                        if r["url"] not in seen:
                            seen.add(r["url"]); results.append(r)
                except Exception as e:
                    log.warning("search failed (%s): %s", q, e)
            all_items.extend(_curate(ask, topic, profile, days, results, per_topic))
        except Exception as e:
            log.warning("Sweep failed for topic %r (provider=%s): %s", topic, provider, e)
    return all_items[:max_items]
