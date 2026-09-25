"""PyInstaller entry point.

Ported from Prospector's installer\prospector_launcher.py -- same reasoning
applies unchanged: a frozen build has no console by default, so anything
that would normally be printed has to go somewhere the user can find, and a
failure to start shows a message box rather than vanishing silently.

TechRadar's own config.py already creates ~/.techradar and loads its .env
as an import-time side effect, so this launcher doesn't need an explicit
ensure_dirs()/load_env() call the way Prospector's and JobPilot's do --
importing techradar.webui is enough to trigger it.
"""

from __future__ import annotations

import os
import sys
import traceback
import webbrowser
from pathlib import Path
from threading import Timer


def _log_path() -> Path:
    folder = Path.home() / ".techradar"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "startup.log"


def _show_error(message: str) -> None:
    """Tell the user something, even with no console attached."""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None,
            f"TechRadar could not start.\n\n{message}\n\n"
            f"Details were written to:\n{_log_path()}",
            "TechRadar", 0x10,
        )
    except Exception:  # noqa: BLE001 - not on Windows, or no user32
        print(message, file=sys.stderr)


def _warn_if_playwright_browser_missing() -> None:
    """crawl4ai (used for non-YouTube link enrichment and GitHub Trending)
    drives Playwright under the hood, which needs a real Chromium that
    PyInstaller does not bundle -- it's a separate download `playwright
    install` manages. Feed scoring and YouTube summaries work without it;
    only page-enrichment needs this. Warn once, don't block startup on it.
    """
    cache = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ms-playwright"
    if cache.exists() and any(cache.iterdir()):
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None,
            "Feed scoring and YouTube summaries will still work, but reading "
            "a shared link's full page text needs a one-time browser "
            "download first. Open a command prompt and run:\n\n"
            "    playwright install chromium\n\n"
            "(This only needs to happen once.)",
            "TechRadar -- one-time setup for link enrichment", 0x40,
        )
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    log = _log_path()
    try:
        sys.stdout = sys.stderr = log.open("w", encoding="utf-8", buffering=1)
    except OSError:
        pass

    try:
        from techradar.webui import create_app

        _warn_if_playwright_browser_missing()
        port = int(os.environ.get("TECHRADAR_PORT", "8766"))
        Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}")).start()
        create_app().run(host="127.0.0.1", port=port, debug=False)
        return 0

    except Exception as exc:  # noqa: BLE001
        traceback.print_exc()
        _show_error(str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
