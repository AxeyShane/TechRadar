from __future__ import annotations

import hashlib
import re
from collections import defaultdict

DIM = 512
_SEED = 0x5EED

_WORD = re.compile(r"[\w]+", re.UNICODE)
# Treat these as stop-ish: skip pure noise for the taste signal
_STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "with", "on", "in",
         "how", "what", "why", "you", "your", "are", "is", "at", "by", "it",
         "this", "that", "vs", "from", "be", "do", "not"}


def _char_ngrams(text: str, lo: int = 3, hi: int = 4) -> list[str]:
    t = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    t = re.sub(r"\s+", " ", t).strip()
    out = []
    for n in range(lo, hi + 1):
        for i in range(0, max(0, len(t) - n) + 1):
            out.append(t[i:i + n])
    return out


def _features(text: str) -> list[str]:
    toks = [w for w in _WORD.findall((text or "").lower()) if w not in _STOP]
    feats = list(toks)
    # word prefixes (len 3-5) so "agent" & "agentic" share signal
    for w in toks:
        for n in (3, 4, 5):
            if len(w) >= n:
                feats.append(w[:n] + "*")
    feats += _char_ngrams(text, 3, 4)
    return feats


def _h(seed: int, t: str) -> int:
    return int(hashlib.md5(f"{seed}:{t}".encode()).hexdigest(), 16)


def _embed(text: str, dim: int = 512, seed: int = _SEED) -> dict[int, float]:
    acc: dict[int, float] = defaultdict(float)
    _ = None
    for f in _features(text):
        idx = _h(seed, f) % dim
        acc[idx] += 1.0
    n = sum(v * v for v in acc.values()) ** 0.5
    return {k: v / n for k, v in acc.items()} if n else {}


def embed(text: str, dim: int = 512) -> dict[int, float]:
    return _embed(text, dim)


def cosine(a: dict[int, float], b: dict[int, float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(av * b.get(i, 0.0) for i, av in a.items())
    na = sum(v * v for v in a.values()) ** 0.5
    nb = sum(v * v for v in b.values()) ** 0.5
    return dot / (na * nb) if (na and nb) else 0.0


def _text_of(it) -> str:
    if isinstance(it, str):
        return it
    return f"{it.get('title','')} {it.get('summary','')} {it.get('reason','')}"


def taste_vector(positive, negative, weights: float = 1.0) -> dict[int, float]:
    pos_w, neg_w = float(weights), float(weights) / 3.0
    acc = defaultdict(float)
    for it in positive:
        for k, v in _embed(_text_of(it)).items():
            acc[k] += v * pos_w
    for it in negative:
        for k, v in _embed(_text_of(it)).items():
            acc[k] -= v * neg_w
    n = sum(v * v for v in acc.values()) ** 0.5
    return {k: v / n for k, v in acc.items()} if n else {}


def rank_feed_by_affinity(items, taste, *, min_score=6, cap=25, score_weight=0.2):
    out = []
    for it in items:
        if it.get("seen"):
            continue
        if (it.get("fit_score") or 0) < min_score:
            continue
        sim = cosine(_embed(_text_of(it)), taste)
        norm_score = (it.get("fit_score") or 0) / 10.0
        it["_sim"] = round(sim, 4)
        it["_rec_rank"] = round((1 - score_weight) * sim + score_weight * norm_score, 4)
        out.append(it)
    out.sort(key=lambda x: x["_rec_rank"], reverse=True)
    return out[:cap]
