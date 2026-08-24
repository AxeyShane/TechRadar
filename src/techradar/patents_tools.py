"""Optional authoritative patent backend (Google Patents public index).

Used only as a LOW-FREQUENCY cross-check: Google Patents aggressively rate-limits
(IP-level 503s once you burst), so keep calls tiny and spaced. A daily run with
a handful of queries is fine; hammering is not.
"""

import logging
import re
import time
import urllib.parse

import httpx

log = logging.getLogger(__name__)

BASE = "https://patents.google.com/xhr/query"
PAGE_BASE = "https://patents.google.com/patent/{}"
RETRIES = 2
BACKOFF = 3.0


def search_google_patents(query: str, num: int = 10) -> list[dict]:
    q = urllib.parse.quote(f"q={query}&num={num}", safe="")
    url = f"{BASE}?url={q}"
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
    last: Exception | None = None
    for attempt in range(RETRIES):
        try:
            resp = httpx.get(url, headers=headers, timeout=25.0)
            if resp.status_code == 200 and resp.text.lstrip().startswith("{"):
                data = resp.json()
                out = []
                for cluster in (data.get("results", {}).get("cluster") or []):
                    for item in (cluster.get("result") or []):
                        p = item.get("patent")
                        if p:
                            out.append(_normalize(p))
                return out
            last = RuntimeError(f"status {resp.status_code}")
        except (httpx.HTTPError, ValueError) as e:
            last = e
        time.sleep(BACKOFF * (attempt + 1))
    log.warning("Google Patents unavailable (%s)", last)
    return []


def _normalize(p: dict) -> dict:
    pub = (p.get("publication_number") or "").strip() or str(p.get("id", ""))
    assignee = p.get("assignee") or ""
    if isinstance(assignee, list):
        assignee = ", ".join(str(a) for a in assignee)
    return {
        "publication_number": pub,
        "title": (p.get("title") or "").strip(),
        "assignee": str(assignee).strip(),
        "publication_date": (p.get("publication_date") or "")[:10],
        "language": p.get("language") or "",
        "snippet": re.sub(r"\s+", " ", (p.get("snippet") or "")).strip()[:400],
        "url": PAGE_BASE.format(pub) if pub else "",
    }
