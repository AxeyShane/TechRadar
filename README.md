# TechRadar

Personal front-row feed for new technology. Pulls from Hacker News, GitHub
Trending, ArXiv, Reddit, and any blogs/YouTube channels you name -- scores
each item against your own interest profile with an LLM, and shows the
ranked result in a small local dashboard. The agent reads/watches, you skim
the front page.

## Setup

```
pip install -e .
# optional local transcription engine:
uv pip install -e ".[transcribe]"
```

Copy `.env.example` to `~/.techradar/.env` and set your LLM provider
(OpenRouter or a local llama.cpp server both work -- same
`LLM_URL`/`LLM_MODEL`/`LLM_API_KEY` pattern).

Edit `config/sources.yaml` and `config/interests.yaml` to taste. To bulk-add
YouTube channels (a Google Takeout `subscriptions.csv` export, or a plain
text/markdown file of channel URLs), run:

```
python scripts/import_youtube_subscriptions.py path/to/file
```

## Use

```
techradar fetch                  # pull sources, score, store new items
techradar web                    # dashboard at http://127.0.0.1:8766
techradar backfill <channel>     # catch up on a YouTube channel's full history
techradar review-profile         # propose learned notes from dismiss + share history
techradar notes-list             # list learned notes (--status proposed|approved|rejected)
techradar notes-approve <id>     # approve a note -- starts affecting scoring
techradar notes-reject <id>      # reject a note
```

## Front-row extras (added 2026-08-17)

- **`techradar sweep`** — proactive discovery *beyond your feeds*. Goes OUT
  and finds NEW items on `discovery.topics` (default provider `llm` = your
  OpenRouter/local LLM + keyless DuckDuckGo-lite search; `--provider mixedbread`
  uses Mixedbread TOAST-1 as the reasoning model, `MIXEDBREAD_API_KEY`).
  `--dry-run` shows the plan without cost. Verified: returns real, on-topic
  candidates with grounded "why" lines.
- **`techradar patents`** — the earliest "front row": surfaces newly-published
  patents in your domains (`patents.keywords`) the day coverage appears,
  curated+scored by your LLM -- ahead of the explainer videos. Verified: caught
  the Bambu multi-nozzle space (WIPO WO2025/218590). Run daily to stay ahead.
- **`techradar share <url>`** — drop any interesting link in; TechRadar
  analyzes it (YouTube: captions then local transcription; other pages:
  crawl4ai text -> chunked LLM summary), scores it like a feed item, and
  shows *why* it matters to you. Also from the dashboard share box, the
  Android Share target, and `/share?url=...`.
- **`techradar transcribe <url|--path>`** — local video/audio -> transcript
  (and `--srt`) via yt-dlp + faster-whisper on your GPU/CPU, cached in SQLite.
  This is the "the agent listens so you don't have to" core: a video with no
  captions still becomes a grounded summary via local ASR.
- **Mobile + PWA** — `techradar web --host 0.0.0.0`, open on your phone,
  "Add to Home Screen": installable app with an Android *Share -> TechRadar*
  target (iOS: bookmarklet `http://<host>:8766/share?url=<url>`).
- **`review-profile` learns from shares too** — explicitly-shared items are
  positive signal; it proposes "boost" notes alongside dismissal-based
  "exclude" notes.
- **Home-server ready** — one Flask process + SQLite + `~/.techradar/.env`;
  runs unchanged on an always-on box at home. Only opted-in services talk to
  the network (OpenRouter, Mixedbread, patent/web search).


- **`/watch` — the self-hosted player.** Link in the dashboard toolbar. Watch
  videos from your own channels without opening YouTube: click a video, it
  streams inline (stream extracted keylessly via yt-dlp, same technique
  NewPipeExtractor uses). Recording watch history is automatic (the "Learn
  from what you actually watch" signal): watched videos feed the scorer's
  relevance prompt and `review-profile`'s boost notes, and the page shows a
  "Because you've watched…" suggestions list (unseen items boosted by
  affinity to what you watched). No phone, no Android app -- just a browser.


> **Watch + YouTube 403s:** YouTube rate-limits bare clients by IP (it 403s this
> machine's traffic after heavy use -- the same long-documented TechRadar
> constraint). The Watch app is built to be robust against it: it downloads to
> a local cache and plays locally (Range/seek), retries transient 403s, and
> uses cookies when provided. To dodge the blocks in normal use, export your
> logged-in YouTube cookies to a Netscape `cookies.txt` and set
> `WATCH_COOKIES_FILE=<path>` (or `WATCH_COOKIES_BROWSER=chrome`) in
> `~/.techradar/.env`. A few watches/day is fine; this session's block was
> caused by dozens of rapid extractions.

## Environment keys (`~/.techradar/.env`)

| Key | Use |
|---|---|
| `LLM_URL` / `LLM_MODEL` / `LLM_API_KEY` | scoring / summarization / sweep planning+curation (OpenRouter or local llama.cpp) |
| `MIXEDBREAD_API_KEY` | optional TOAST-1 as the sweep reasoning model (`provider: mixedbread`) |
| `WHISPER_MODEL` | faster-whisper size for local transcription (default `medium`) |
| `DISCOVERY_PROVIDER` | default sweep provider (`llm` \| `mixedbread`) |
| `SHARE_ANALYZE_ON_SHARE` | set `0` to skip background analysis on share (headless) |

> Note: as of 2026-08-17 the active LLM provider is OpenRouter
> (`google/gemini-2.5-flash-lite`). The previous local llama.cpp config
> (`http://127.0.0.1:8082`, `smollm3-3b`) is preserved commented in `.env`.
> TOAST-1's hosted function-calling harness currently 500s on custom tools, so
> `mixedbread` is used as a plain reasoning model -- `llm` is the reliable default.

## Notes

- YouTube IP-blocks the transcript endpoint after sustained high-volume
  requests; local transcription (`transcriber.py`) is the fallback that keeps
  scoring grounded in content regardless.
- DuckDuckGo **html** search returns 202 challenge pages under automation;
  sweeps use **lite** (`search_web`), which is scrape-friendly.
- Google Patents (authoritative US/EP/WIPO/CN index) rate-limits aggressively;
  it's an optional, low-frequency cross-check (`patents.google_patents: true`),
  not the primary patent source.
