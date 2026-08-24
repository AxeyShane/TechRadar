"""Recency-aware, source-capped ranking for the TechRadar feed.

Pure functions over already-fetched item rows, so the ranking policy is
unit-testable without a DB or LLM. The dashboard applies these to the
ranked feed; the mobile surface is the same code (one responsive page).

Deliberately keeps signal-over-volume: a source can only fill a slice of
the page, and an older high score decays so a fresh medium score can
outrank it.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from typing import Any, Sequence


def _epoch(ts: str | float | None, default: float) -> float:
    """Parse a discovered_at/published_at string to a unix epoch."""
    if ts is None:
        return default
    if isinstance(ts, (int, float)):
        return float(ts)
    s = str(ts).strip()
    # Handle both 'YYYY-MM-DDTHH:MM:SS' and 'YYYY-MM-DD HH:MM:SS' + optional 'Z'/offset.
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return default


def now_epoch() -> float:
    return time.time()


def recency_decay(
    score: float | None,
    discovered_ts: float | None,
    now: float | None = None,
    half_life_days: float = 14.0,
    min_score_floor: float = 0.0,
) -> float:
    """Decay a fit score by how stale it is.

    A score from `half_life_days` ago is worth half.  The decay multiplies
    the raw score (1.0 = today), so a fresh 7 can beat a very stale 9.
    Returns score unchanged when there's no time anchor or no score.
    """
    if score is None or discovered_ts is None:
        return score if score is not None else min_score_floor
    now = now_epoch() if now is None else now
    age_days = max(0.0, (now - discovered_ts) / 86400.0)
    factor = math.pow(0.5, age_days / max(half_life_days, 1e-9))
    return score * factor


def apply_source_caps(
    ranked: Sequence[dict],
    cap: int,
    source_key: str = "source",
) -> list[dict]:
    """Keep at most `cap` items from any one source, preserving order."""
    if cap <= 0:
        return list(ranked)
    seen = {}
    out = []
    for item in ranked:
        src = item.get(source_key) or "?"
        if seen.get(src, 0) >= cap:
            continue
        seen[src] = seen.get(src, 0) + 1
        out.append(item)
    return out


def rank_feed(
    items: Sequence[dict],
    *,
    min_score: int = 6,
    limit: int = 200,
    source_cap: int = 5,
    half_life_days: float = 14.0,
    now: float | None = None,
) -> list[dict]:
    """Full feed-rank pass: filter by min, decay by recency, cap per source.

    Returns the ranked list (already capped) with the effective decayed
    score attached to each item as `_rank_score` (and the decayed score on
    `fit_score` so the UI can render it). The raw score is preserved on
    `_raw_score`.
    """
    now_t = now_epoch() if now is None else now
    eligible = [
        it
        for it in items
        if (it.get("fit_score") or 0) >= min_score
    ]
    for it in eligible:
        it["_raw_score"] = it.get("fit_score")
        it["_rank"] = recency_decay(
            it.get("fit_score"),
            _epoch(it.get("discovered_at"), now_t),
            now=now_t,
            half_life_days=half_life_days,
        )
    ranked = sorted(eligible, key=lambda it: (it["_rank"], it.get("discovered_at") or ""), reverse=True)
    ranked = apply_source_caps(ranked, source_cap)
    return ranked[:limit]
