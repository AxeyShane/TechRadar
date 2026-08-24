"""Scores each fetched item against the user's interest profile, 1-10."""

import json
import logging
import re

from techradar.llm import get_client

log = logging.getLogger(__name__)

SCORE_PROMPT = """You are filtering a tech news feed for one specific reader.

READER'S INTERESTS:
{profile}
{notes_block}
{watched_block}
ITEM:
Source: {source}
Title: {title}
Summary: {summary}

Score how interesting this item is to THIS reader, 1-10 (10 = drop everything
and read this now, 1 = totally irrelevant). Judge against their stated
interests, not generic tech-newsworthiness.

Return ONLY valid JSON: {{"score": <1-10 integer>, "reason": "<under 15 words>"}}
No explanation, no markdown, no code fences."""


def _extract_json(text: str) -> dict:
    text = text.strip()
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    text = text.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        text = match.group(0)
    return json.loads(text)


def score_item(item: dict, profile: str, notes: list[str] | None = None,
                watched: list[str] | None = None) -> tuple[int, str]:
    """Returns (score, reason). Falls back to (0, error) on failure so a bad
    item never crashes the batch -- it just won't surface. `notes` are
    approved learned exclusions/boosts from the dismiss-feedback loop;
    `watched` are titles of videos the reader actually watched (strong
    positive signal: judge relevance partly by resemblance to what they
    watch)."""
    notes_block = ""
    if notes:
        notes_block = "\nLEARNED EXCLUSIONS (from your dismiss history):\n" + "\n".join(
            f"- {n}" for n in notes
        ) + "\n"
    watched_block = ""
    if watched:
        watched_block = "\nREADER RECENTLY WATCHED (what they watch is what they want; score bearing this in mind):\n" + "\n".join(
            f"- {w[:120]}" for w in watched
        ) + "\n"
    prompt = SCORE_PROMPT.format(
        profile=profile,
        notes_block=notes_block,
        watched_block=watched_block,
        source=item.get("source", "?"),
        title=item.get("title", "")[:300],
        summary=item.get("summary", "")[:600],
    )
    try:
        client = get_client()
        raw = client.ask(prompt, temperature=0.0, max_tokens=200)
        result = _extract_json(raw)
        score = int(result.get("score", 0))
        reason = str(result.get("reason", ""))[:200]
        return max(0, min(10, score)), reason
    except Exception as e:
        log.warning("Scoring failed for %s: %s", item.get("url", "?"), e)
        return 0, f"scoring error: {e}"[:200]
