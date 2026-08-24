"""One-off: bulk-add YouTube channels into config/sources.yaml's feeds: list.
Appends only -- never touches existing entries or comments, since a full
yaml round-trip would strip them. Two input shapes:

1. A Google Takeout subscriptions.csv export (Channel Id, Channel Url,
   Channel Title columns) -- channel_id already known, no network needed.
2. A plain text/markdown file, one channel URL/@handle per line -- each
   gets resolved to a channel_id + display name via yt-dlp (~1-2s/channel).

Usage: python scripts/import_youtube_subscriptions.py path/to/file
"""

import csv
import sys
from pathlib import Path

SOURCES_YAML = Path(__file__).resolve().parent.parent / "config" / "sources.yaml"


def feed_url(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def resolve_handle(url: str) -> tuple[str, str] | None:
    """URL/@handle -> (channel_id, display_name), or None if resolution fails
    (private/deleted/renamed channel -- skip rather than crash the batch)."""
    from yt_dlp import YoutubeDL
    opts = {"extract_flat": True, "quiet": True, "skip_download": True, "playlist_items": "0"}
    try:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        channel_id = info.get("channel_id") or info.get("id")
        name = info.get("channel") or info.get("uploader") or channel_id
        return (channel_id, name) if channel_id else None
    except Exception as e:
        print(f"  skip {url}: {e}")
        return None


def rows_from_csv(path: Path) -> list[tuple[str, str]]:
    rows = list(csv.reader(path.read_text(encoding="utf-8-sig").splitlines()))
    if rows and rows[0] and rows[0][0].strip().lower() in ("channel id", "channel_id"):
        rows = rows[1:]  # skip header if present
    result = []
    for row in rows:
        if not row or not row[0].strip().startswith("UC"):
            continue
        channel_id, _url, title = (row + ["", "", ""])[:3]
        result.append((channel_id.strip(), title.strip() or channel_id.strip()))
    return result


def rows_from_url_list(path: Path) -> list[tuple[str, str]]:
    urls = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"Resolving {len(urls)} channel(s) via yt-dlp...")
    result = []
    for i, url in enumerate(urls, 1):
        resolved = resolve_handle(url)
        if resolved:
            result.append(resolved)
        if i % 10 == 0:
            print(f"  ...{i}/{len(urls)}")
    return result


def main(path_str: str) -> None:
    path = Path(path_str)
    text = SOURCES_YAML.read_text(encoding="utf-8")
    existing_ids = {line.split("channel_id=")[1].split('"')[0].strip() for line in text.splitlines()
                     if "channel_id=" in line}

    is_csv_export = path.suffix.lower() == ".csv"
    rows = rows_from_csv(path) if is_csv_export else rows_from_url_list(path)

    new_lines = []
    skipped = 0
    for channel_id, title in rows:
        if not channel_id or channel_id in existing_ids:
            skipped += 1
            continue
        existing_ids.add(channel_id)
        safe_title = title.replace('"', "'")
        new_lines.append(f'  - name: "{safe_title}"\n    url: "{feed_url(channel_id)}"\n')

    if not new_lines:
        print(f"Nothing new to add (skipped {skipped} already present).")
        return

    text = text.rstrip("\n") + "\n" + "".join(new_lines)
    SOURCES_YAML.write_text(text, encoding="utf-8")
    print(f"Added {len(new_lines)} channels, skipped {skipped} already present.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python scripts/import_youtube_subscriptions.py path/to/file")
        sys.exit(1)
    main(sys.argv[1])
