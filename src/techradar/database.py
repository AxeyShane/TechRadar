"""SQLite storage for scored tech-news items."""

import sqlite3

from techradar.config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    url TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    published_at TEXT,
    fit_score INTEGER,
    reason TEXT,
    discovered_at TEXT NOT NULL,
    seen INTEGER NOT NULL DEFAULT 0,
    shared INTEGER NOT NULL DEFAULT 0,
    note TEXT
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'proposed',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS transcripts (
    key TEXT PRIMARY KEY,
    source_url TEXT,
    title TEXT,
    text TEXT NOT NULL,
    segments_json TEXT,
    language TEXT,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watched (
    video_id TEXT PRIMARY KEY,
    url TEXT,
    title TEXT NOT NULL,
    channel TEXT,
    channel_id TEXT,
    watched_at TEXT NOT NULL,
    progress REAL DEFAULT 0
);
"""

_ITEM_COLUMNS = ("shared", "note")  # added to pre-existing DBs via migration


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    # Migration: pre-existing items tables lack the newer columns.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(items)").fetchall()}
    for col in _ITEM_COLUMNS:
        if col not in existing:
            ctype = "INTEGER NOT NULL DEFAULT 0" if col == "shared" else "TEXT"
            conn.execute(f"ALTER TABLE items ADD COLUMN {col} {ctype}")
    conn.commit()
    return conn


def item_exists(conn: sqlite3.Connection, url: str) -> bool:
    row = conn.execute("SELECT 1 FROM items WHERE url = ?", (url,)).fetchone()
    return row is not None


def store_item(conn: sqlite3.Connection, item: dict) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO items "
        "(url, source, title, summary, published_at, fit_score, reason, discovered_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            item["url"], item["source"], item["title"], item.get("summary", ""),
            item.get("published_at"), item.get("fit_score"), item.get("reason", ""),
            item["discovered_at"],
        ),
    )
    conn.commit()


def get_ranked_items(conn: sqlite3.Connection, min_score: int = 0, limit: int = 100) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT * FROM items WHERE fit_score >= ? ORDER BY fit_score DESC, discovered_at DESC LIMIT ?",
        (min_score, limit),
    ).fetchall()


def mark_seen(conn: sqlite3.Connection, url: str) -> None:
    conn.execute("UPDATE items SET seen = 1 WHERE url = ?", (url,))
    conn.commit()


def get_stats(conn: sqlite3.Connection) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    scored = conn.execute("SELECT COUNT(*) FROM items WHERE fit_score IS NOT NULL").fetchone()[0]
    surfaced = conn.execute("SELECT COUNT(*) FROM items WHERE fit_score >= 6").fetchone()[0]
    return {"total": total, "scored": scored, "surfaced": surfaced}


def add_note(conn: sqlite3.Connection, kind: str, text: str, evidence: str) -> int:
    from datetime import datetime, timezone
    cur = conn.execute(
        "INSERT INTO notes (kind, text, evidence, status, created_at) VALUES (?, ?, ?, 'proposed', ?)",
        (kind, text, evidence, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    return cur.lastrowid


def list_notes(conn: sqlite3.Connection, status: str | None = None) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    if status:
        return conn.execute(
            "SELECT * FROM notes WHERE status = ? ORDER BY created_at DESC", (status,)
        ).fetchall()
    return conn.execute("SELECT * FROM notes ORDER BY created_at DESC").fetchall()


def set_note_status(conn: sqlite3.Connection, note_id: int, status: str) -> None:
    conn.execute("UPDATE notes SET status = ? WHERE id = ?", (status, note_id))
    conn.commit()


# ---------------------------------------------------------------------------
# Shared-inbox (share-to-TechRadar) + transcript cache
# ---------------------------------------------------------------------------

def store_shared(conn: sqlite3.Connection, url: str, title: str = "", note: str = "") -> bool:
    """Insert an item explicitly shared by the user (e.g. from a phone share
    sheet). Stored unscored (fit_score NULL) so it lands in the inbox until
    analysis has run. Returns False if the URL is already tracked."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT OR IGNORE INTO items "
        "(url, source, title, summary, published_at, fit_score, reason, discovered_at, seen, shared, note) "
        "VALUES (?, 'shared', ?, '', NULL, NULL, '', ?, 0, 1, ?)",
        (url, title or url, now, note),
    )
    conn.commit()
    return cur.rowcount == 1


def get_shared_items(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT rowid AS id, * FROM items WHERE shared = 1 "
        "ORDER BY discovered_at DESC LIMIT ?",
        (limit,),
    ).fetchall()


def update_item_after_analysis(conn: sqlite3.Connection, url: str, item: dict) -> None:
    """Fill in title/summary/score/reason once a shared item has been analyzed."""
    conn.execute(
        "UPDATE items SET title = ?, summary = ?, fit_score = ?, reason = ? WHERE url = ?",
        (item.get("title") or url, item.get("summary", ""), item.get("fit_score"), item.get("reason", ""), url),
    )
    conn.commit()


def get_transcript(conn: sqlite3.Connection, key: str) -> sqlite3.Row | None:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT * FROM transcripts WHERE key = ?", (key,)
    ).fetchone()


def store_transcript(conn: sqlite3.Connection, key: str, source_url: str, title: str,
                     text: str, segments_json: str | None, language: str | None,
                     model: str) -> None:
    from datetime import datetime, timezone
    conn.execute(
        "INSERT OR REPLACE INTO transcripts "
        "(key, source_url, title, text, segments_json, language, model, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (key, source_url, title, text, segments_json, language, model,
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Watch history (the "learn from what you actually watch" signal)
# ---------------------------------------------------------------------------

def store_watched(conn: sqlite3.Connection, video_id: str, url: str, title: str,
                  channel: str = "", channel_id: str = "", progress: float = 0.0) -> bool:
    """Record a watched video (upsert keyed by video_id). Returns True if new."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO watched (video_id, url, title, channel, channel_id, watched_at, progress) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(video_id) DO UPDATE SET watched_at=excluded.watched_at, progress=excluded.progress",
        (video_id, url, title, channel or "", channel_id or "", now, progress),
    )
    conn.commit()
    row = conn.execute("SELECT 1 FROM watched WHERE video_id=?", (video_id,)).fetchone()
    return row is not None


def is_watched(conn: sqlite3.Connection, video_id: str) -> bool:
    return conn.execute("SELECT 1 FROM watched WHERE video_id=?", (video_id,)).fetchone() is not None


def get_watched(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(
        "SELECT * FROM watched ORDER BY watched_at DESC LIMIT ?", (limit,)
    ).fetchall()


def get_watched_channels(conn: sqlite3.Connection, limit: int = 20) -> dict[str, int]:
    """channel_id -> watch count (affinity for suggestions)."""
    rows = conn.execute(
        "SELECT channel_id, COUNT(*) n FROM watched WHERE channel_id IS NOT NULL AND channel_id != '' "
        "GROUP BY channel_id ORDER BY n DESC, MAX(watched_at) DESC LIMIT ?", (limit,)
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def get_watched_titles(conn: sqlite3.Connection, limit: int = 15) -> list[str]:
    rows = conn.execute(
        "SELECT title FROM watched ORDER BY watched_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [r[0] for r in rows if r[0]]


def get_approved_notes(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT text FROM notes WHERE status = 'approved'").fetchall()
    return [r[0] for r in rows]
