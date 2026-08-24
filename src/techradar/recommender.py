"""Feedback loop: turn dismiss history into discrete, curated notes.

Kept as its own module (not folded into scorer.py/pipeline.py) so the
feedback strategy can be swapped later -- e.g. for an embeddings/similarity
recommender -- without touching the fetch/score pipeline. Only the two
functions below are the contract: gather signal in, proposed notes out.
Never writes interests.yaml directly; the user approves/rejects each note
via `techradar notes-approve`/`notes-reject` before it affects scoring.

Small evidence-backed notes instead of one rewritten profile blob, so each
change is individually reviewable instead of a diff-less wall of prose.
"""

import logging
import sqlite3

from techradar.llm import get_client
from techradar.scorer import _extract_json

log = logging.getLogger(__name__)

MAX_NOTES_PER_RUN = 5

PROPOSAL_PROMPT = """You are refining a tech-news reader's interest profile
based on their actual behavior, not just what they originally wrote.

CURRENT PROFILE:
{profile}

ALREADY LEARNED (don't repeat these, propose only genuinely new notes):
{existing_notes}

ITEMS THEY DISMISSED (despite the current profile scoring them well enough
to surface):
{dismissed_list}

ITEMS THEY EXPLICITLY SHARED FOR ANALYSIS (strong positive signal -- the
profile is under-serving these / he liked them enough to share them):
{shared_list}

VIDEOS THEY ACTUALLY WATCHED (the strongest positive signal: this is what he
consumes in reality -- boost notes should reflect these):
{watched_list}

Dismissals are negative signal (profile over-scores this kind of item);
shares are positive signal (profile under-serves this kind of item). Propose
at most {max_notes} short, discrete notes that would (a) reduce future false
positives from the dismissals and (b) boost patterns the shares reveal.
Each note is either "exclude" (score lower) or "boost" (score higher).
Ground every note in the actual items given.

Return ONLY this JSON object, no preamble, no markdown fences:
{{"notes": [{{"kind": "exclude"|"boost", "text": "<one short sentence>", "evidence_titles": ["<title>", ...]}}]}}"""


def gather_dismissed(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT title, source, fit_score, reason FROM items "
        "WHERE seen = 1 ORDER BY discovered_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def gather_watched(conn: sqlite3.Connection, limit: int = 30) -> list[dict]:
    """Videos the user actually watched (NewPipe-style watch history) -- the
    strongest positive interest signal we have."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT title, channel, channel_id, watched_at FROM watched "
        "ORDER BY watched_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def gather_shared(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    """Analyzed items the user explicitly shared -- positive interest signal."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT title, source, fit_score, reason, note FROM items "
        "WHERE shared = 1 AND fit_score IS NOT NULL "
        "ORDER BY discovered_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def propose_notes(profile: str, dismissed: list[dict], existing_notes: list[str],
                  shared: list[dict] | None = None,
                  watched: list[dict] | None = None) -> list[dict]:
    """Returns a list of {"kind", "text", "evidence_titles"} dicts, capped
    at MAX_NOTES_PER_RUN. Empty list if there's no signal or the LLM call
    fails/returns something unparseable -- never raises."""
    if not dismissed and not shared and not watched:
        return []

    dismissed_list = "\n".join(
        f"- [{d['source']}] {d['title']} (scored {d['fit_score']}/10, reason: {d['reason']})"
        for d in dismissed
    ) or "(none)"
    shared_list = "\n".join(
        f"- [{s['source']}] {s['title']} (scored {s['fit_score']}/10, note: {s.get('note') or ''})"
        for s in (shared or [])
    ) or "(none)"
    watched_list = "\n".join(
        f"- [{w['channel'] or 'watch history'}] {w['title']}"
        for w in (watched or [])
    ) or "(none)"
    existing_block = "\n".join(f"- {n}" for n in existing_notes) if existing_notes else "(none yet)"
    prompt = PROPOSAL_PROMPT.format(
        profile=profile,
        existing_notes=existing_block,
        dismissed_list=dismissed_list,
        shared_list=shared_list,
        watched_list=watched_list,
        max_notes=MAX_NOTES_PER_RUN,
    )
    try:
        raw = get_client().ask(prompt, temperature=0.2, max_tokens=800)
        result = _extract_json(raw)
        notes = result.get("notes", [])
        if not isinstance(notes, list):
            return []
        return notes[:MAX_NOTES_PER_RUN]
    except Exception as e:
        log.warning("Note proposal failed: %s", e)
        return []


if __name__ == "__main__":
    # Self-check: malformed/empty LLM output must never raise. Patches the
    # module-global directly (not via mock.patch's dotted path) since
    # `python -m` runs this file as a separate __main__ module object --
    # patching "techradar.recommender.get_client" would patch a distinct,
    # freshly re-imported module instance, not the one executing here.
    class _FakeClient:
        def ask(self, *args, **kwargs):
            return "not json at all"

    get_client = lambda: _FakeClient()  # noqa: E731 -- shadows the module import for this check only
    result = propose_notes("profile", [{"title": "x", "source": "y", "fit_score": 7, "reason": "z"}], [])
    assert result == [], f"expected [] on unparseable response, got {result!r}"
    print("OK")
