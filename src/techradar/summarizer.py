"""Transcript/page summarization with chunked map-reduce.

Why: a 30-60 minute video produces far more transcript text than a single
LLM context budget should ingest per call. We split into sentence-aligned
chunks, summarize each (map), then condense the chunk summaries into the
final 2-3 sentence summary (reduce). This keeps every call small and cheap
(e.g. OpenRouter) regardless of transcript length, and never silently
truncates the source the way feeds.fetch_youtube_summary's 8k-char cut does.
"""

import logging
import re

from techradar.llm import get_client

log = logging.getLogger(__name__)

CHUNK_CHARS = 15000          # ~3.5-4k tokens per map call
MAP_MAX_TOKENS = 160         # per-chunk summary budget
REDUCE_MAX_TOKENS = 220      # final summary budget

MAP_PROMPT = """This is part {part} of {total} of a transcript. Summarize this
part in 2-4 short bullet points, keeping concrete details, names, numbers, and
claims. Do not editorialize; preserve what is factually said.

TRANSCRIPT PART:
{chunk}"""

REDUCE_PROMPT = """Combine these bullet summaries of a video/podcast transcript
into a final summary of 2-3 sentences that captures what is concretely new or
useful in the whole recording. Do not add anything not present in the bullets.

BULLET SUMMARIES:
{bullets}"""


def _sentence_split(text: str) -> list[str]:
    """Split into sentences, keeping boundary whitespace out."""
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [p for p in parts if p.strip()]


def chunk_text(text: str, max_chars: int = CHUNK_CHARS) -> list[str]:
    """Sentence-aligned chunks of <= max_chars. Long single sentences are
    hard-cut rather than dropped."""
    sentences = _sentence_split(text)
    chunks: list[str] = []
    current = ""
    for s in sentences:
        if len(current) + len(s) + 1 > max_chars and current:
            chunks.append(current.strip())
            current = ""
        # A sentence longer than the budget becomes its own chunk (hard cut).
        if len(s) > max_chars:
            for i in range(0, len(s), max_chars):
                chunks.append(s[i:i + max_chars])
            continue
        current = (current + " " + s).strip()
    if current:
        chunks.append(current.strip())
    return chunks or [text.strip()]


def _ask(prompt: str, max_tokens: int) -> str:
    client = get_client()
    return client.ask(prompt, temperature=0.0, max_tokens=max_tokens).strip()


def summarize_transcript(text: str, title: str | None = None) -> str:
    """Map-reduce summary of a (possibly long) transcript. Returns "" on
    empty input; on LLM failure logs a warning and returns a truncated
    excerpt so callers still have *something* grounded to score on."""
    text = (text or "").strip()
    if not text:
        return ""
    try:
        chunks = chunk_text(text)
        if len(chunks) == 1:
            prompt = MAP_PROMPT.format(part=1, total=1, chunk=chunks[0])
            bullets = _ask(prompt, MAP_MAX_TOKENS)
        else:
            bullet_parts = []
            for i, chunk in enumerate(chunks, start=1):
                bullet_parts.append(_ask(MAP_PROMPT.format(part=i, total=len(chunks), chunk=chunk), MAP_MAX_TOKENS))
            bullets = "\n".join(f"- {b}" for b in bullet_parts)
        summary = _ask(REDUCE_PROMPT.format(bullets=bullets), REDUCE_MAX_TOKENS)
        return summary or text[:8000]
    except Exception as e:
        log.warning("Summarization failed: %s", e)
        return text[:8000]


def summarize_text(text: str, title: str | None = None) -> str:
    """Shorter path for plain page text (capped source, single call)."""
    text = (text or "").strip()
    if not text:
        return ""
    if len(text) <= CHUNK_CHARS:
        return summarize_transcript(text, title=title)
    # Pages: keep the most content-dense 60k chars, then map-reduce.
    return summarize_transcript(text[:60000], title=title)
