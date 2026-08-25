import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from techradar import recommend

def _item(i, title, score=7, src="youtube", seen=False):
    return {"id": i, "title": title, "summary": "", "reason": "",
            "fit_score": score, "source": src, "seen": seen,
            "discovered_at": "2026-08-24T00:00:00"}

def test_embed_deterministic_normalized():
    a = recommend.embed("agent LLM serving")
    b = recommend.embed("agent LLM serving")
    assert a == b
    n = sum(v*v for v in a.values())**0.5
    assert abs(n - 1.0) < 1e-6

def test_cosine_similar_semantics():
    a = recommend.embed("agentic AI coding tool for developers")
    b = recommend.embed("building agents AI workflows")
    c = recommend.embed("baking sourdough bread at home")
    assert recommend.cosine(a, b) > recommend.cosine(a, c)

def test_taste_vector_and_ranking():
    taste = recommend.taste_vector(
        positive=["training agents to complete tasks with tools"],
        negative=["funding round announcement"],
    )
    items = [
        _item(1, "how agents complete tasks using tools", 7),
        _item(2, "Series B funding for a chip startup", 9),
        _item(3, "A concrete guide to tool-using LLM agents", 7),
        _item(4, "seen one", 8, seen=True),
    ]
    ranked = recommend.rank_feed_by_affinity(items, taste, min_score=6, cap=10, score_weight=0.15)
    ids = [it["id"] for it in ranked]
    assert ids.index(1) < ids.index(2)
    assert ids.index(3) < ids.index(2)
    assert 4 not in ids
    assert all(it["_sim"] is not None for it in ranked)

def test_empty_taste_no_crash():
    assert recommend.rank_feed_by_affinity([], {}) == []

def test_unseen_only():
    taste = recommend.taste_vector(["agents tools"], [])
    items = [_item(1,"x agents",7,seen=False), _item(2,"y agents",7,seen=True)]
    out = recommend.rank_feed_by_affinity(items, taste)
    assert all(it["seen"] is False for it in out)
