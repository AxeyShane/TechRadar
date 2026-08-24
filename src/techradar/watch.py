"""Watch webapp for TechRadar: play videos (via yt-dlp stream extraction,
same keyless approach NewPipeExtractor uses), record watch history, and
suggest what to watch next -- learning from what you actually watched.

This is the "instead of going to YouTube to watch it" piece: a self-hosted
player page in TechRadar. No phone, no Android app -- a browser webapp.
"""

import logging
import re

from techradar.config import load_interests
from techradar.database import get_connection

log = logging.getLogger(__name__)

YT_ID_RE = re.compile(r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([\w-]{11})")


def video_id(url: str) -> str | None:
    m = YT_ID_RE.search(url or "")
    return m.group(1) if m else None


def _pick_stream(info: dict) -> str:
    """Choose a single playable stream URL from yt-dlp info. Prefer a merged
    (video+audio) mp4 <=1080p, else any merged <=1080p, else a 720p mp4, else
    the default best video URL. Raises if nothing usable."""
    formats = info.get("formats") or []
    if not formats:
        url = info.get("url")
        if url:
            return url
        raise RuntimeError("no playable stream found")

    def merged(f):
        return f.get("vcodec", "none") != "none" and f.get("acodec", "none") != "none"

    def height_of(f):
        return f.get("height") or 0

    def mp4(f):
        return "mp4" in (f.get("ext") or "").lower()

    merged_ok = [f for f in formats if merged(f) and height_of(f) <= 1080]
    if merged_ok:
        mp4s = [f for f in merged_ok if mp4(f)]
        pick = sorted(mp4s or merged_ok, key=lambda f: (mp4(f), height_of(f)))[-1]
        return pick["url"]
    # separate streams: fall back to a 720p mp4 if present, else best video
    vids = [f for f in formats if f.get("vcodec", "none") != "none"]
    for f in sorted(vids, key=lambda f: height_of(f), reverse=True):
        if mp4(f) and height_of(f) <= 1080:
            return f["url"]
    top = sorted(vids, key=lambda f: height_of(f), reverse=True)
    url = top[0].get("url") if top else info.get("url")
    if url:
        return url
    raise RuntimeError("no playable stream found")


def extract_stream(url: str, height: int = 1080) -> dict:
    """Extract a direct playable stream + metadata for a video URL via yt-dlp.
    Best-effort; raises on failure (caller surfaces a friendly message)."""
    import yt_dlp
    opts = {
        "format": f"best[height<={height}]/best",
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "nocheckcertificate": True,
    }
    _apply_cookies(opts)
    info = None
    last_err = None
    for attempt in (0, 1):  # retry once -- YouTube 403s are often transient
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            break
        except Exception as e:
            last_err = e
            time.sleep(4)
    if info is None:
        raise RuntimeError(f"yt-dlp extraction failed: {str(last_err)[:140]}")
    stream = _pick_stream(info)
    hdrs = info.get("http_headers") or {}
    if not hdrs and info.get("formats"):
        hdrs = info["formats"][0].get("http_headers") or {}
    return {
        "url": stream,
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "channel_id": info.get("channel_id") or "",
        "duration": info.get("duration"),
        "thumbnail": info.get("thumbnail"),
        "video_id": video_id(url) or info.get("id"),
        "http_headers": hdrs,
    }


_feed_cache: dict = {"ts": 0.0, "items": []}
_FEED_TTL = 600.0   # seconds


def recent_feed(limit: int = 30, use_cache: bool = True):
    """Latest videos from the user's subscribed channels, via their RSS feeds
    (fetched CONCURRENTLY, cached for _FEED_TTL seconds) with watched flags."""
    import time
    from concurrent.futures import ThreadPoolExecutor
    import feedparser
    from techradar.config import load_sources

    if use_cache and time.time() - _feed_cache["ts"] < _FEED_TTL:
        return _feed_cache["items"]

    feeds = (load_sources().get("feeds") or [])
    yt_feeds = [f for f in feeds if "youtube.com/feeds/videos.xml" in (f.get("url") or "")][:limit]

    def fetch_one(f):
        try:
            d = feedparser.parse(f["url"])
        except Exception:
            return []
        out = []
        for e in d.entries[:3]:
            url = e.get("link") or ""
            vid = video_id(url)
            if vid:
                out.append({
                    "url": url, "video_id": vid,
                    "title": e.get("title", ""),
                    "channel": f.get("name", ""),
                    "channel_id": (e.get("yt_channelid") or ""),
                    "published": e.get("published", "")[:16],
                    "watched": False,
                })
        return out

    with ThreadPoolExecutor(max_workers=12) as ex:
        chunks = list(ex.map(fetch_one, yt_feeds))
    items = [it for chunk in chunks for it in chunk]

    conn = get_connection()
    try:
        watched_ids = {r[0] for r in conn.execute("SELECT video_id FROM watched").fetchall()}
    finally:
        conn.close()
    for it in items:
        it["watched"] = it["video_id"] in watched_ids

    _feed_cache["ts"] = time.time()
    _feed_cache["items"] = items
    return items[:200]


def is_watched(conn, vid: str) -> bool:
    from techradar import database
    return bool(vid) and database.is_watched(conn, vid)




# ---------------------------------------------------------------------------
# Download-then-play (reliable path for long content)
# ---------------------------------------------------------------------------

import os as _os
import threading as _threading
import time as _time
from techradar.config import APP_DIR


def _apply_cookies(opts: dict) -> None:
    """Attach YouTube cookies to yt-dlp opts to dodge the notorious IP
    403/throttling. Env: WATCH_COOKIES_FILE (Netscape cookies.txt) or
    WATCH_COOKIES_BROWSER (e.g. chrome, edge, firefox). Best-effort."""
    f = _os.environ.get("WATCH_COOKIES_FILE", "").strip()
    b = _os.environ.get("WATCH_COOKIES_BROWSER", "").strip()
    if f:
        opts["cookiefile"] = f
    elif b:
        try:
            opts["cookiesfrombrowser"] = (b,)
        except Exception:
            pass

CACHE_DIR = _os.environ.get("WATCH_CACHE_DIR") or str(APP_DIR / "watch_cache")
CACHE_MAX_BYTES = int(_os.environ.get("WATCH_CACHE_MAX_GB", "6")) * 1024**3
_dl: dict = {}                 # video_id -> state
_dl_lock = _threading.Lock()


def _cache_path(video_id: str) -> str:
    import pathlib
    pathlib.Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    return _os.path.join(CACHE_DIR, video_id + ".mp4")


def media_ready(video_id: str) -> str | None:
    path = _cache_path(video_id)
    return path if _os.path.exists(path) else None


def _cleanup_cache():
    """Keep the cache under CACHE_MAX_BYTES: delete oldest files first."""
    import pathlib
    files = [p for p in pathlib.Path(CACHE_DIR).glob("*.mp4")]
    total = sum(p.stat().st_size for p in files)
    if total <= CACHE_MAX_BYTES:
        return
    for p in sorted(files, key=lambda f: f.stat().st_mtime):
        if total <= CACHE_MAX_BYTES:
            break
        try:
            total -= p.stat().st_size
            p.unlink()
        except OSError:
            pass


def download_for_play(url: str, video_id: str, height: int = 720) -> dict:
    """Download a playable copy to CACHE_DIR in a background thread, updating
    _dl state. Single merged format (video+audio) so no ffmpeg is needed.
    Returns the current state dict."""
    with _dl_lock:
        state = _dl.get(video_id)
        if state and state.get("status") in ("downloading", "ready"):
            return state
        state = {"status": "downloading", "pct": 0.0, "path": None, "err": None}
        _dl[video_id] = state

    def work():
        import yt_dlp
        dst = _cache_path(video_id)
        opts = {
            "format": f"best[height<={height}][ext=mp4][vcodec!=none][acodec!=none]/"
                      f"18/best[height<={height}]/best",
            "outtmpl": dst,
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "nocheckcertificate": True,
        }
        _apply_cookies(opts)
        def hook(d):
            if d.get("status") == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                done = d.get("downloaded_bytes") or 0
                state["pct"] = (done / total) if total else 0.0
            elif d.get("status") == "finished":
                state["pct"] = 1.0
        opts["progress_hooks"] = [hook]
        try:
            last = None
            for attempt in (0, 1):
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        ydl.extract_info(url, download=True)
                    break
                except Exception as e:
                    last = e
                    _time.sleep(4)
            else:
                raise last
            
            # yt-dlp may have written with a different container ext
            import glob
            candidates = glob.glob(dst.rsplit(".", 1)[0] + ".*")
            final = None
            for c in candidates:
                if c.lower().endswith((".mp4", ".webm", ".m4a")):
                    final = c
                    break
            if final and final != dst:
                _os.replace(final, dst)
            if not _os.path.exists(dst):
                raise RuntimeError("download produced no file")
            state["status"] = "ready"
            state["path"] = dst
            state["pct"] = 1.0
            _cleanup_cache()
        except Exception as e:
            state["status"] = "error"
            state["err"] = str(e)[:160]

    _threading.Thread(target=work, daemon=True).start()
    return state


def dl_status(video_id: str) -> dict:
    st = dict(_dl.get(video_id) or {"status": "unknown", "pct": 0.0, "err": None, "path": None})
    path = media_ready(video_id)
    if path and st.get("status") != "downloading":
        st["status"] = "ready"
        st["path"] = path
        st["pct"] = 1.0
    return st


def suggestions(limit: int = 12) -> list[dict]:
    """'Because you watched X' -- unseen scored items, boosted by lightweight
    keyword affinity to what you've watched. Deterministic (no extra LLM call),
    so the suggestions page stays instant and free."""
    from techradar import database
    from techradar.config import load_interests

    min_score = load_interests().get("min_score", 6)
    conn = database.get_connection()
    try:
        watched = database.get_watched(conn, limit=10)
        cur = conn.execute(
            "SELECT * FROM items WHERE fit_score >= ? AND seen = 0 "
            "ORDER BY fit_score DESC, discovered_at DESC LIMIT 80", (min_score,)
        )
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    finally:
        conn.close()

    watched_titles = [w["title"].lower() for w in watched]
    scored = []
    for it in rows:
        title = (it.get("title") or "").lower()
        overlap = sum(1 for wt in watched_titles
                      if wt and len(wt) >= 8 and wt.split()[:3]
                      and any(w in title for w in wt.split() if len(w) >= 5))
        boost = min(overlap, 2)
        scored.append((it["fit_score"] + boost, it))
    scored.sort(key=lambda x: x[0], reverse=True)
    out = scored[:limit]
    return [dict(it) for _, it in out]
