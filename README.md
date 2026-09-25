<div align="center">

# 📡 TechRadar

**Your personal front-row feed for new technology.**
The agent reads and watches — you skim the front page.

![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/dashboard-Flask-000000?logo=flask&logoColor=white)
![SQLite](https://img.shields.io/badge/storage-SQLite-003B57?logo=sqlite&logoColor=white)
![Version](https://img.shields.io/badge/version-0.1.0-informational)
[![License](https://img.shields.io/badge/license-MIT-yellow)](LICENSE)

[Quick start](#-quick-start) •
[Usage](#%EF%B8%8F-usage) •
[Features](#-features) •
[Configuration](#%EF%B8%8F-configuration) •
[Windows installer](#-windows-installer) •
[Android](#-android-companion) •
[Notes](#-notes--known-limits)

</div>

---

TechRadar pulls from **Hacker News, GitHub Trending, ArXiv, Reddit**, and any
**blogs / YouTube channels** you name, scores each item against *your own*
interest profile with an LLM, and shows the ranked result in a small local
dashboard.

- 🎯 **Scored by your interests**, not an engagement algorithm
- 🎧 **Grounded in content** — videos are summarized from full transcripts (local Whisper when captions are blocked)
- 🔭 **Goes beyond your feeds** — discovery sweeps, patent watch, similar-channel suggestions
- 🏠 **Runs at home** — one Flask process + SQLite, works on an always-on box

---

## 🚀 Quick start

**Prerequisites:** [Python 3.11+](https://www.python.org/downloads/), [Git](https://git-scm.com/downloads),
and an LLM — a free [OpenRouter](https://openrouter.ai/keys) key *or* a local
OpenAI-compatible server (llama.cpp, Ollama).

### 1. Clone and install

```powershell
git clone https://github.com/AxeyShane/TechRadar.git
cd TechRadar

python -m venv .venv
.venv\Scripts\activate           # macOS/Linux: source .venv/bin/activate

pip install -e .
```

Optional — local transcription engine (faster-whisper, GPU or CPU):

```bash
pip install -e ".[transcribe]"
```

### 2. Configure your LLM

Copy `.env.example` to `~/.techradar/.env` and fill in `LLM_URL`, `LLM_MODEL`
and `LLM_API_KEY`:

```powershell
mkdir $HOME\.techradar -Force
copy .env.example $HOME\.techradar\.env
notepad $HOME\.techradar\.env
```

```bash
# macOS/Linux
mkdir -p ~/.techradar && cp .env.example ~/.techradar/.env
```

### 3. Pick your sources and interests

Edit **`config/sources.yaml`** (feeds, channels, discovery topics) and
**`config/interests.yaml`** (what you care about).

To bulk-add YouTube channels from a Google Takeout `subscriptions.csv` or a
plain text/markdown list of channel URLs:

```bash
python scripts/import_youtube_subscriptions.py path/to/file
```

### 4. Fetch and open the dashboard

```bash
techradar fetch      # pull sources, score, store new items
techradar web        # open http://127.0.0.1:8766
```

> [!TIP]
> On Windows, **`techradar-web.bat`** / **`start_techradar.bat`** start the
> dashboard for you once the `.venv` exists.

---

## ⌨️ Usage

| Command | What it does |
|---|---|
| `techradar fetch` | Pull sources, score, store new items |
| `techradar web` | Dashboard at http://127.0.0.1:8766 (`--host 0.0.0.0` for phone access) |
| `techradar backfill <channel>` | Catch up on a YouTube channel's full history |
| `techradar sweep` | Find **new** items on your discovery topics, beyond your feeds (`--dry-run` to preview) |
| `techradar patents` | Surface newly-published patents in your domains |
| `techradar share <url>` | Analyze and score any link you drop in |
| `techradar transcribe <url\|--path>` | Local video/audio → transcript (`--srt` supported) |
| `techradar review-profile` | Propose learned notes from dismiss + share history |
| `techradar notes-list` | List learned notes (`--status proposed\|approved\|rejected`) |
| `techradar notes-approve <id>` | Approve a note — starts affecting scoring |
| `techradar notes-reject <id>` | Reject a note |
| `techradar discover-channels` | Find **new** YouTube channels similar to the ones you watch most |
| `techradar channels-list` | List channel-discovery suggestions |
| `techradar channels-approve <id>` | Approve one — adds it to your feeds |
| `techradar channels-reject <id>` | Reject one |

---

## ✨ Features

### 🔭 Discovery beyond your feeds — `techradar sweep`

Goes **out** and finds new items on `discovery.topics`. Default provider `llm`
uses your OpenRouter/local LLM plus keyless DuckDuckGo-lite search;
`--provider mixedbread` uses Mixedbread TOAST-1 as the reasoning model
(`MIXEDBREAD_API_KEY`). `--dry-run` shows the plan without cost. Returns real,
on-topic candidates with grounded "why" lines.

### 📜 Patent watch — `techradar patents`

The earliest "front row": surfaces newly-published patents in your domains
(`patents.keywords`) the day coverage appears, curated and scored by your LLM —
ahead of the explainer videos. (It caught the Bambu multi-nozzle space,
WIPO WO2025/218590.) Run daily to stay ahead.

### 🔗 Share anything — `techradar share <url>`

Drop in any link. TechRadar analyzes it (YouTube: captions, then local
transcription; other pages: crawl4ai text → chunked LLM summary), scores it
like a feed item, and shows *why* it matters to you. Also available from the
dashboard share box, the Android **Share → TechRadar** target, and
`/share?url=...`.

### 🎧 Grounded scoring everywhere

`fetch`, `backfill`, `sweep` and `patents` run every YouTube item through the
same untruncated captions → map-reduce summary the share flow uses, falling
back to local ASR when captions are blocked. Local ASR is gated by the
`transcription:` block in `config/sources.yaml` (per-run cap plus a cheap
title-only prescore, so Whisper only runs on videos worth the cost).

### 🎙️ Local transcription — `techradar transcribe`

yt-dlp + faster-whisper on your GPU/CPU, cached in SQLite. The "agent listens
so you don't have to" core: a video with no captions still becomes a grounded
summary.

### ▶️ `/watch` — the self-hosted player

Linked from the dashboard toolbar. Watch videos from your channels without
opening YouTube:

- Streams inline (extracted keylessly via yt-dlp), cached locally with seek support
- **Watch history is recorded automatically** and feeds the scorer and `review-profile`'s boost notes
- **"Because you've watched…"** suggestions, ranked by a local taste vector
  (watch/share history minus dismissals — no extra LLM call), excluding videos
  you've already seen and pulling your top-affinity channels directly
- **"Latest from your channels"** scans a rotating window across your *full*
  subscription list and sorts by real publish date
- 5-second cancelable **"Up next"** card with optional autoplay
- **Discover channels** panel with inline Approve / Dismiss

### 🧭 Similar-channel discovery — `techradar discover-channels`

No keyless "similar channels" API exists, so it works like `sweep`: the LLM
plans search queries from your watch history, DuckDuckGo-lite runs them, each
result is resolved to a real channel via yt-dlp, and the LLM curates the fit.

Suggestions land as `status=proposed` and **never touch your feeds until you
review them**. Approved channels go into `config/discovered_channels.yaml` — a
separate machine-owned file merged in by `load_sources()` — so your
hand-curated `sources.yaml` is never auto-edited. Configure via the
`channel_discovery:` block (provider, max_candidates).

### 🎨 A front row that looks like one

Real thumbnails (YouTube frame, or a colored initial tile for
articles/papers/patents), a **"Today's top pick"** hero card, category-color
dots (video / paper / patent / discussion / code / article), and
`j` / `k` / `enter` / `x` keyboard navigation. Still no algorithm beyond your
own interest profile and your own watch/share/dismiss history.

### 🧠 It learns from you

`review-profile` treats explicitly-shared items as positive signal, proposing
"boost" notes alongside dismissal-based "exclude" notes. Nothing affects
scoring until you approve it.

### 📱 Mobile + PWA

Run `techradar web --host 0.0.0.0`, open it on your phone and **Add to Home
Screen** — an installable app with an Android *Share → TechRadar* target.
iOS: bookmarklet `http://<host>:8766/share?url=<url>`.

### 🏠 Home-server ready

One Flask process + SQLite + `~/.techradar/.env` runs unchanged on an
always-on box. Only opted-in services talk to the network (OpenRouter,
Mixedbread, patent/web search).

---

## ⚙️ Configuration

### Environment keys — `~/.techradar/.env`

| Key | Use |
|---|---|
| `LLM_URL` / `LLM_MODEL` / `LLM_API_KEY` | Scoring, summarization, sweep planning + curation (OpenRouter or local llama.cpp) |
| `MIXEDBREAD_API_KEY` | Optional TOAST-1 as the sweep reasoning model (`provider: mixedbread`) |
| `WHISPER_MODEL` | faster-whisper size for local transcription (default `medium`) |
| `DISCOVERY_PROVIDER` | Default sweep provider (`llm` \| `mixedbread`) |
| `SHARE_ANALYZE_ON_SHARE` | Set `0` to skip background analysis on share (headless) |
| `WATCH_COOKIES_FILE` | Netscape `cookies.txt` of your logged-in YouTube session — dodges IP 403s on `/watch`, downloads and transcription |
| `WATCH_COOKIES_BROWSER` | Alternative: browser yt-dlp pulls cookies from directly (`chrome`, `edge`, `firefox`) |

All of these are documented in `.env.example`.

> [!NOTE]
> Default provider is OpenRouter (`google/gemini-2.5-flash-lite`). A local
> llama.cpp server works the same way — just point `LLM_URL` at it (e.g.
> `http://127.0.0.1:8082`). TOAST-1's hosted function-calling harness currently
> 500s on custom tools, so `mixedbread` is used as a plain reasoning model —
> `llm` is the reliable default.

### `config/sources.yaml` blocks

- **`transcription:`** — gates the local-Whisper fallback. `max_per_fetch`
  caps how many videos one run transcribes; `min_prescore` skips ASR on
  anything that wouldn't score well anyway. Requires the `[transcribe]` extra;
  silently skipped otherwise.
- **`scheduler:`** — optional in-process auto-refresh so `techradar web` keeps
  itself current. **Off by default** (it spends LLM budget and YouTube
  requests) — enable with `scheduler.enabled: true`. On a headless box, prefer
  cron-ing `techradar fetch` / `techradar patents`.
- **`channel_discovery:`** — provider and `max_candidates` for
  `discover-channels`.

> [!WARNING]
> **YouTube 403s.** YouTube rate-limits bare clients by IP after heavy use.
> `/watch` downloads to a local cache, retries transient 403s, and uses cookies
> when provided. To avoid blocks, export your logged-in YouTube cookies to a
> Netscape `cookies.txt` and set `WATCH_COOKIES_FILE=<path>` (or
> `WATCH_COOKIES_BROWSER=chrome`). A few watches a day is fine; dozens of rapid
> extractions is not.

---

## 🪟 Windows installer

`installer/` has a PyInstaller + Inno Setup pipeline (ported from Prospector's)
that builds a standalone **`TechRadarSetup.exe`** — no Python needed on the
target machine:

```powershell
powershell -ExecutionPolicy Bypass -File installer\build_installer.ps1
```

<details>
<summary>Caveats</summary>

- Not yet published as a release download — build it yourself for now.
- Budget some debugging time on the first build: `crawl4ai` hasn't been frozen
  with PyInstaller in this portfolio before.
- Feed scoring and YouTube summaries work without a browser installed; reading
  a shared link's full page text needs a one-time
  `playwright install chromium`, which the app prompts for.
- The `[transcribe]` extra (faster-whisper) is deliberately **not** bundled —
  it's opt-in from source only.

</details>

---

## 📱 Android companion

`android/` is a thin WebView client for the dashboard. It needs TechRadar
already running somewhere reachable (`techradar web --host 0.0.0.0`) — it
doesn't run TechRadar itself.

```bash
python android/build_apk.py
```


---

## 📝 Notes & known limits

- **YouTube** IP-blocks the transcript endpoint after sustained high-volume
  requests; local transcription (`transcriber.py`) keeps scoring grounded
  regardless.
- **DuckDuckGo html** search returns 202 challenge pages under automation;
  sweeps use **lite** (`search_web`), which is scrape-friendly.
- **Google Patents** rate-limits aggressively; it's an optional, low-frequency
  cross-check (`patents.google_patents: true`), not the primary patent source.


---

<div align="center">
<sub>Built by <a href="https://github.com/AxeyShane">@AxeyShane</a> · MIT License · © 2026 Akshay Kharvi</sub>
</div>
