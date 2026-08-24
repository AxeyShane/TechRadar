"""Local video/audio -> transcript (and SRT/VTT) via yt-dlp + faster-whisper.

The "listen for the agent" core: download the audio with yt-dlp (already a
TechRadar dependency), transcribe it locally with faster-whisper (CTranslate2:
CUDA GPU when present, CPU otherwise), and cache the result in SQLite so a
video is never transcribed twice. Works for any URL yt-dlp understands:
YouTube, Drive, Zoom, direct web video/audio, local files.

faster-whisper is an *optional* dependency ([project.optional-dependencies]
transcribe) so TechRadar's core stays lightweight; callers get a clear error
if it isn't installed.
"""

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path

from techradar.config import load_interests
from techradar.database import get_connection, get_transcript, store_transcript
from techradar.sources.feeds import youtube_video_id
from techradar.summarizer import summarize_transcript

log = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("WHISPER_MODEL", "medium")
AUDIO_FORMATS = (".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac", ".aac", ".mp4", ".mkv", ".webm")


def _transcript_key(url_or_path: str) -> str:
    vid = youtube_video_id(url_or_path)
    if vid:
        return f"yt:{vid}"
    return "file:" + hashlib.sha1(url_or_path.encode("utf-8")).hexdigest()[:16]


def _model_and_segmenter(model_name: str):
    """Import faster-whisper lazily; raise a helpful error if unavailable."""
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        raise RuntimeError(
            "faster-whisper is not installed. Run:  uv pip install -e '.[transcribe]'  "
            "(or: pip install faster-whisper) inside the TechRadar venv."
        )
    return WhisperModel(model_name, device="auto", compute_type="auto")


def download_audio(url: str, workdir: Path) -> Path:
    """Download the best audio stream for a URL into workdir. Returns the
    media file path; raises on failure with the yt-dlp error."""
    import yt_dlp  # already a TechRadar dependency

    outtmpl = str(workdir / "%(id)s.%(ext)s")
    opts = {
        "format": "bestaudio/best",
        "outtmpl": outtmpl,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "nocheckcertificate": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        if not info:
            raise RuntimeError(f"yt-dlp returned no media info for {url}")
        path = Path(ydl.prepare_filename(info))
        if not path.exists():
            # yt-dlp may have picked a format whose actual ext differs
            candidates = sorted(workdir.glob("*.{mkv,webm,m4a,mp3,opus,wav,mp4}"), key=lambda p: -p.stat().st_size)
            if not candidates:
                raise RuntimeError(f"Downloaded audio file missing for {url}")
            path = candidates[0]
        return path


def transcribe(url: str | None = None, path: str | None = None,
               model: str = DEFAULT_MODEL, language: str | None = None,
               use_cache: bool = True) -> dict:
    """Transcribe media from a URL (yt-dlp) or a local file. Returns
    {key, text, segments, language, model, duration}. Reads/writes the
    SQLite transcript cache (skip with use_cache=False)."""
    if not url and not path:
        raise ValueError("Provide either url= or path=")
    source = url or path
    key = _transcript_key(source)
    conn = get_connection()
    try:
        if use_cache:
            cached = get_transcript(conn, key)
            if cached and cached["model"] == model:
                return {
                    "key": key, "text": cached["text"],
                    "segments": json.loads(cached["segments_json"] or "[]"),
                    "language": cached["language"], "model": model,
                    "duration": None,
                }
    finally:
        conn.close()

    model_obj, segment_iter = None, None
    tmpdir = None
    media_path: Path | None = None
    try:
        if url:
            tmpdir = Path(tempfile.mkdtemp(prefix="techradar-"))
            media_path = download_audio(url, tmpdir)
        else:
            media_path = Path(path)

        model_obj = _model_and_segmenter(model)
        segments_it, info = model_obj.transcribe(
            str(media_path),
            language=language,
            vad_filter=True,
            beam_size=5,
        )
        segments = [
            {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            for s in segments_it
        ]
        text = " ".join(sg["text"] for sg in segments).strip()
        detected_lang = getattr(info, "language", None)
        duration = getattr(info, "duration", None)
    finally:
        if tmpdir and tmpdir.exists():
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    result = {
        "key": key, "text": text, "segments": segments,
        "language": detected_lang, "model": model, "duration": duration,
    }
    conn = get_connection()
    try:
        store_transcript(conn, key, source, "", text,
                         json.dumps(segments, ensure_ascii=False), detected_lang, model)
    finally:
        conn.close()
    return result


def transcribe_and_summarize(url: str, model: str = DEFAULT_MODEL) -> str | None:
    """Transcribe a video URL and summarize it via the LLM (OpenRouter/local).
    Returns None when transcription fails (caller keeps what it already had)."""
    try:
        result = transcribe(url=url, model=model)
        if not result.get("text"):
            return None
        interests = load_interests()
        title = interests.get("profile", "")  # not the video title; kept opaque
        return summarize_transcript(result["text"], title=None)
    except Exception as e:
        log.warning("Local transcription failed for %s: %s", url, e)
        return None


def _srt_ts(sec: float) -> str:
    ms = int(round((sec % 1) * 1000))
    s = int(sec) % 60
    m = (int(sec) // 60) % 60
    h = int(sec) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def segments_to_srt(segments: list[dict]) -> str:
    lines = []
    for i, sg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(f"{_srt_ts(sg['start'])} --> {_srt_ts(sg['end'])}")
        lines.append(sg["text"])
        lines.append("")
    return "\n".join(lines)


def segments_to_vtt(segments: list[dict]) -> str:
    lines = ["WEBVTT", ""]
    for sg in segments:
        lines.append(f"{_srt_ts(sg['start']).replace(',', '.')} --> {_srt_ts(sg['end']).replace(',', '.')}")
        lines.append(sg["text"])
        lines.append("")
    return "\n".join(lines)
