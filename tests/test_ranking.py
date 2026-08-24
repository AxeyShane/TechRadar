import os, sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from techradar import ranking


def _days(i, score, source, days_ago=0):
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {"id": i, "fit_score": score, "source": source, "title": f"item{i}",
            "discovered_at": ts}


def test_recency_decay_today_is_unchanged():
    s = ranking.recency_decay(8, ranking.now_epoch())
    assert s == 8.0


def test_recency_decay_older_halves():
    now = ranking.now_epoch()
    stale = now - 14 * 86400
    assert ranking.recency_decay(8, stale, now=now, half_life_days=14) == pytest.approx(4.0)


def test_rank_fresh_beats_stale():
    fresh = _days(1, 7, "a", 0)
    stale = _days(2, 9, "a", 60)
    out = ranking.rank_feed([stale, fresh], min_score=6)
    assert [it["id"] for it in out] == [1, 2]


def test_source_cap_limits_one_source():
    a = [_days(i, 8, "youtube", 0) for i in range(10)]
    b = [_days(100, 8, "arxiv", 0)]
    out = ranking.rank_feed(a + b, source_cap=3)
    srcs = [it["source"] for it in out]
    assert srcs.count("youtube") == 3
    assert srcs.count("arxiv") == 1


def test_min_score_filters():
    out = ranking.rank_feed([_days(1, 5, "a"), _days(2, 7, "b")], min_score=6)
    assert [it["id"] for it in out] == [2]


def test_limit_respected():
    items = [_days(i, 8, "s" + str(i % 3), 0) for i in range(50)]
    out = ranking.rank_feed(items, limit=20, source_cap=100)
    assert len(out) == 20


def test_raw_score_preserved():
    out = ranking.rank_feed([_days(1, 7, "a", 30)], min_score=6)
    assert out[0]["_raw_score"] == 7
