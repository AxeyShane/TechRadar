"""Downloader for TechRadar: save feed media the TubeMate way.

Download a video from a feed item as MP4 (merged video+audio, no ffmpeg
needed) or MP3 (audio-only). Reuses watch.py's proven approach (cookies,
transient-403 retry, merged single format) so it stays robust against
YouTube's IP throttling, and bounds the size so a mis-tap can't pull a
huge file. The server does the heavy lifting; the dashboard/APK requests a
download and the server streams the saved file back via /api/download/media.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time as _time

from techradar.config import APP_DIR

log = logging.getLogger(__name__)

DOWNLOAD_DIR = os.environ.get("TECHRADAR_DOWNLOAD_DIR") or str(APP_DIR / "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
MAX_MB = int(os.environ.get("TECHRADAR_DOWNLOAD_MAX_MB", "2000"))

_YT_QUERY = re.compile(r"(?:[?&]v=|/shorts/|/embed/)([\w-]{11})")
_YT_BE = re.compile(r"youtu\.be/([\w-]{11})")


def video_id(url: str):
    if not url:
        return None
    m = _YT_QUERY.search(url) or _YT_BE.search(url)
    return m.group(1) if m else None


def _safe_name(url: str, vid: str) -> str:
    h = hashlib.sha256((url or "").encode()).hexdigest()[:8]
    return f"{vid or 'item'}_{h}"


def _apply_cookies(opts: dict) -> None:
    f = os.environ.get("WATCH_COOKIES_FILE", "").strip()
    b = os.environ.get("WATCH_COOKIES_BROWSER", "").strip()
    if f:
        opts["cookiefile"] = f
    elif b:
        cracks = [p.strip() for p in b.split(",") if p.strip()]
        if cracks:
            opts["cookiesfrombrowser"] = (cracks[0],)


_DL: dict = {}
_LOCK = threading.Lock()


def download(url: str, fmt: str = "mp4", height: int = 720) -> dict:
    """Start a background download. fmt: 'mp4' | 'mp3'. Returns state dict."""
    vid = video_id(url)
    key = f"{_safe_name(url, vid)}__{fmt}"
    with _LOCK:
        state = _DL.get(key)
        if state and state.get("status") in ("downloading", "done"):
            return state
        state = {"status": "queued", "pct": 0.0, "path": None, "err": None,
                 "fmt": fmt, "id": vid}
        _DL[key] = state

    def work():
        import yt_dlp
        import glob
        base = os.path.join(DOWNLOAD_DIR, _safe_name(url, vid or "item"))
        if fmt == "mp4":
            outtmpl = base + ".mp4"
            fmt_spec = (
                f"best[height<={height}][ext=mp4][vcodec!=none][acodec!=none]/18/"
                f"best[height<={height}]/best"
            )
        else:  # mp3
            outtmpl = base + ".%(ext)s"
            fmt_spec = "bestaudio/best"
        opts = {
            "format": fmt_spec,
            "outtmpl": outtmpl,
            "quiet": True, "no_warnings": True, "noplaylist": True,
            "nocheckcertificate": True,
            "max_filesize": MAX_MB * 1024 * 1024,
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
            final_path = None
            last = None
            for attempt in (0, 1):
                try:
                    with yt_dlp.YoutubeDL(opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                    break
                except Exception as e:
                    last = e
                    _time.sleep(4)
            else:
                raise last

            # Locate the written file (yt-dlp may pick a container ext).
            base_noext = base.rsplit(".", 1)[0]
            candidates = glob.glob(base_noext + ".*")
            for c in candidates:
                if c.lower().endswith((".mp4", ".webm", ".m4a", ".mp3")):
                    final_path = c
                    break
            if not final_path or not os.path.exists(final_path):
                # fall back to whatever exists
                final_path = base + ".mp4" if fmt == "mp4" else None
            if not final_path or not os.path.exists(final_path):
                raise RuntimeError("download produced no file")

            # Optional MP3 conversion if ffmpeg is present.
            if fmt == "mp3":
                final_path = _maybe_mp3(final_path, base + ".mp3")

            state["status"] = "done"
            state["path"] = final_path
            state["pct"] = 1.0
        except Exception as e:
            state["status"] = "error"
            state["err"] = str(e)[:200]

    threading.Thread(target=work, daemon=True).start()
    return state


def _maybe_mp3(audio_path: str, mp3_path: str) -> str:
    """Convert an audio file to MP3 if ffmpeg is available; else keep it."""
    import shutil
    ff = shutil.which("ffmpeg")
    if not ff or audio_path.lower().endswith(".mp3"):
        return audio_path
    try:
        import subprocess
        r = subprocess.run([ff, "-y", "-i", audio_path, "-codec:a", "libmp3lame", "-q:a", "2", mp3_path],
                           capture_output=True, timeout=600)
        if r.returncode == 0 and os.path.exists(mp3_path):
            return mp3_path
    except Exception as e:
        log.warning("mp3 conversion failed: %s", e)
    return audio_path


def status(filename: str) -> dict:
    key = filename
    return dict(_DL.get(key) or {"status": "unknown"})


def list_files() -> list[dict]:
    out = []
    for f in sorted(os.listdir(DOWNLOAD_DIR)):
        p = os.path.join(DOWNLOAD_DIR, f)
        if os.path.isfile(p):
            out.append({"name": f, "size": os.path.getsize(p),
                        "mtime": os.path.getmtime(p)})
    return out


def file_path(filename: str) -> str | None:
    p = os.path.join(DOWNLOAD_DIR, filename)
    return p if os.path.isfile(p) and os.path.realpath(p).startswith(os.path.realpath(DOWNLOAD_DIR)) else None
