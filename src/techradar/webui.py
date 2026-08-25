"""Minimal Flask dashboard: ranked feed, mark-seen, on-demand refresh."""

import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, request

from techradar import database
from techradar.config import load_interests

# short-lived stream tokens: token -> {url, headers, ts} (proxy uses yt-dlp's exact headers)
_proxy_tokens: dict = {}
import time as _time
import secrets as _secrets

WATCH_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>TechRadar \u00b7 Watch</title>
<style>
  :root{--bg:#fff;--surface:#f7f7f5;--border:#dcdcd6;--text:#16181d;--muted:#6b6b66;--accent:#3b5bfd;--radius:10px;}
  *{box-sizing:border-box} body{font-family:-apple-system,system-ui,sans-serif;background:var(--bg);color:var(--text);
    margin:0;padding:1.5rem;max-width:960px;margin-inline:auto;}
  h1{font-size:1.3rem;margin:0 0 .2rem} .sub{color:var(--muted);font-size:.85rem;margin-bottom:1rem}
  a.back{color:var(--muted);font-size:.8rem;text-decoration:none}
  .player-wrap{background:#000;border-radius:var(--radius);overflow:hidden;margin-bottom:.8rem}
  video{width:100%;display:block;aspect-ratio:16/9;background:#000}
  .now-t{font-weight:600;margin:.2rem 0} .now-c{color:var(--muted);font-size:.8rem}
  h2{font-size:.9rem;color:var(--muted);margin:1.2rem 0 .4rem;font-weight:600}
  .grid{display:grid;grid-template-columns:1fr;gap:.6rem}
  @media(min-width:720px){.grid{grid-template-columns:1fr 1fr}}
  .vid{border:1px solid var(--border);border-radius:var(--radius);padding:.7rem .9rem;background:var(--surface);cursor:pointer}
  .vid:hover{border-color:var(--accent)}
  .vid .t{font-size:.9rem;font-weight:600} .vid .m{color:var(--muted);font-size:.75rem;margin-top:.25rem}
  .badge{display:inline-block;border-radius:999px;padding:.05rem .5rem;font-size:.7rem;border:1px solid var(--border);color:var(--muted)}
  .badge.wat{background:#e6f4ea;color:#1a7431;border-color:var(--border)}
  .err{color:#a33;background:#fdeceb;border:1px solid #f3c6c2;border-radius:var(--radius);padding:.5rem .8rem;font-size:.85rem;margin:.6rem 0}
</style></head><body>
  <h1>TechRadar \u00b7 Watch</h1>
  <div class="sub">Watch from your own channels \u2014 TechRadar learns from what you play.</div>
  <a class="back" href="/">&larr; back to feed</a>
  <div class="player-wrap" id="playerWrap" hidden>
    <video id="video" controls playsinline></video>
  </div>
  <div class="now-t" id="nowTitle"></div>
  <div class="now-c" id="nowChannel"></div>
  <div id="err"></div>
  <h2>Because you've watched\u2026</h2>
  <div class="grid" id="sugg"></div>
  <h2>Latest from your channels</h2>
  <div class="grid" id="feed"></div>
<script>
let currentId=null;
function esc(s){return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function rowHtml(v){return `<div class="vid" data-url="${esc(v.url)}" data-vid="${esc(v.video_id)}" data-title="${esc(v.title)}" data-chan="${esc(v.channel)}" data-cid="${esc(v.channel_id)}">
  <div class="t">${esc(v.title)} <span class="badge ${v.watched?'wat':''}">${v.watched?'watched':'play'}</span></div>
  <div class="m">${esc(v.channel)}${v.published?' \u00b7 '+esc(v.published):''}</div></div>`;}
function bind(){document.querySelectorAll('.vid').forEach(el=>el.onclick=()=>playFrom(el.dataset));}
async function load(){
  const s=await (await fetch('/api/watch/suggestions')).json();
  document.getElementById('sugg').innerHTML=s.items.map(rowHtml).join('')||'<div class="m">Watch a video first \u2014 suggestions appear after your history grows.</div>';
  const f=await (await fetch('/api/watch/feed')).json();
  document.getElementById('feed').innerHTML=f.items.map(rowHtml).join('');
  bind();
}
async function playFrom(d){
  currentId=d.vid; document.getElementById('err').innerHTML='';
  document.getElementById('playerWrap').hidden=false;
  document.getElementById('nowTitle').textContent=d.title+' (preparing…)';
  document.getElementById('nowChannel').textContent=d.chan;
  try{
    const r=await fetch('/api/watch/play',{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({url:d.url,video_id:d.vid})});
    const j=await r.json();
    if(!j.ok){document.getElementById('err').innerHTML='<div class="err">'+esc(j.reason||'failed to start')+'</div>';return;}
    const poll=setInterval(async ()=>{
      const s=await (await fetch('/api/watch/play/status/'+d.vid)).json();
      if(s.media){
        clearInterval(poll);
        document.getElementById('nowTitle').textContent=d.title;
        const v=document.getElementById('video');
        v.onended=()=>record(d,1);
        v.ontimeupdate=()=>{ if(v.currentTime>20 && !v._rec){v._rec=1; record(d, v.currentTime/v.duration||0);} };
        v.src=s.media; v.play().catch(()=>{});
      } else if(s.status==='error'){
        clearInterval(poll);
        document.getElementById('err').innerHTML='<div class="err">'+esc(s.err||'download failed')+'</div>';
      } else {
        document.getElementById('nowTitle').textContent=d.title+' (preparing '+Math.round(s.pct)+'%)';
      }
    },1000);
  }catch(e){document.getElementById('err').innerHTML='<div class="err">'+esc('failed: '+e)+'</div>';}
}
async function record(d,progress){
  await fetch('/api/watch/watched',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({url:d.url,video_id:d.vid,title:d.title,channel:d.chan,channel_id:d.cid,progress})});
  load();
}
load();
</script></body></html>"""


log = logging.getLogger(__name__)

_fetch_lock = threading.Lock()
_fetch_running = False
_fetch_error: str | None = None

_analyze_lock = threading.Lock()
_analyzing: set[str] = set()          # urls currently being analyzed
_analyze_errors: dict[str, str] = {}


def _run_fetch_background():
    global _fetch_running, _fetch_error
    from techradar.pipeline import run
    try:
        run()
    except Exception as e:
        log.error("Background fetch failed: %s", e)
        _fetch_error = str(e)
    finally:
        _fetch_running = False


def _run_analyze_background(url: str, title: str):
    """Analyze one shared URL (transcript/summary + score) off-thread."""
    from techradar import database
    from techradar import enrich
    try:
        item = enrich.analyze_url(url, title)
        conn = database.get_connection()
        database.update_item_after_analysis(conn, url, item)
        conn.close()
        log.info("Shared item analyzed: %s (score=%s)", item["title"][:60], item.get("fit_score"))
    except Exception as e:
        log.error("Analysis failed for %s: %s", url, e)
        _analyze_errors[url] = str(e)
    finally:
        _analyzing.discard(url)


def start_analysis(url: str, title: str = "") -> bool:
    """Kick off background analysis if not already running for this URL."""
    with _analyze_lock:
        if url in _analyzing:
            return False
        _analyzing.add(url)
        threads = list(_analyzing)
        threading.Thread(target=_run_analyze_background, args=(url, title), daemon=True).start()
        return True


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#3b5bfd">
<link rel="manifest" href="/manifest.webmanifest">
<link rel="apple-touch-icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='20' fill='%233b5bfd'/><text x='50' y='68' font-size='52' text-anchor='middle' fill='white' font-family='system-ui' font-weight='700'>T</text></svg>">
<title>TechRadar</title>
<style>
  :root {
    --bg: #ffffff; --surface: #f7f7f5; --border: #dcdcd6;
    --text: #16181d; --text-muted: #6b6b66; --accent: #3b5bfd;
    --ok-bg: #e6f4ea; --ok: #1a7431; --radius: 10px;
    --text-xs: 0.75rem; --text-sm: 0.85rem; --text-lg: 1.1rem; --text-xl: 1.3rem;
  }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, system-ui, sans-serif; background: var(--bg); color: var(--text);
    margin: 0; padding: 2rem; max-width: 900px; margin-inline: auto; }
  h1 { font-size: var(--text-xl); margin: 0 0 0.3rem; }
  .sub { color: var(--text-muted); font-size: var(--text-sm); margin-bottom: 1.5rem; }
  .toolbar { display: flex; gap: 0.6rem; align-items: center; margin-bottom: 0.6rem; flex-wrap: wrap; }
  button { background: var(--accent); color: #fff; border: none; padding: 0.5rem 1rem;
    border-radius: var(--radius); font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
  button:disabled { opacity: 0.5; cursor: default; }
  .stats { color: var(--text-muted); font-size: var(--text-sm); }
  .fetch-error { color: var(--text); background: #fdeceb; border: 1px solid #f3c6c2;
    border-radius: var(--radius); padding: 0.5rem 0.8rem; font-size: var(--text-sm);
    margin-bottom: 1rem; }
  .item { border: 1px solid var(--border); border-radius: var(--radius); padding: 1rem 1.2rem;
    margin-bottom: 0.8rem; background: var(--surface); }
  .item.seen { opacity: 0.45; }
  .item-top { display: flex; justify-content: space-between; align-items: baseline; gap: 1rem; }
  .score { font-weight: 800; font-size: var(--text-lg); color: var(--accent); flex-shrink: 0; }
  .score-unit { font-weight: 600; font-size: var(--text-xs); color: var(--text-muted); }
  .title { font-weight: 600; }
  .title a { color: inherit; text-decoration: none; }
  .title a:hover { text-decoration: underline; }
  .meta { color: var(--text-muted); font-size: var(--text-xs); margin-top: 0.3rem; }
  .reason { font-size: var(--text-sm); color: var(--text-muted); margin-top: 0.4rem; font-style: italic; }
  .dismiss { display: inline-block; background: none; color: var(--text-muted); border: 1px solid var(--border);
    padding: 0.4rem 0.75rem; font-size: var(--text-sm); margin-top: 0.6rem; }
  details.seen-section { margin-top: 1rem; }
  .feed-group { margin-top: 0.6rem; }
  .feed-group + .feed-group { margin-top: 1rem; }
  .group-label { color: var(--text-muted); font-size: var(--text-sm); font-weight: 600;
    margin: 0 0 0.4rem; }
  .row-actions { display: flex; gap: 0.4rem; align-items: center; margin-top: 0.5rem; }
  .ghost.dl { background: transparent; color: var(--text-muted); border: 1px solid var(--border);
    border-radius: 10px; padding: 0.2rem 0.6rem; font-size: 0.75rem; cursor: pointer; }
  .ghost.dl:hover { border-color: var(--text-muted); }
  .dl-status { min-height: 1rem; color: var(--text-muted); font-size: 0.8rem; margin: 0.4rem 0; }
  details.seen-section summary { cursor: pointer; color: var(--text-muted); font-size: var(--text-sm);
    font-weight: 600; padding: 0.4rem 0; }
  .share-box { border: 1px solid var(--border); border-radius: var(--radius); padding: 0.9rem 1rem;
    margin-bottom: 0.8rem; background: var(--surface); }
  .share-box label { font-size: var(--text-sm); color: var(--text-muted); font-weight: 600; }
  .share-row { display: flex; gap: 0.5rem; margin-top: 0.5rem; }
  .share-row input { flex: 1; min-width: 0; border: 1px solid var(--border); border-radius: var(--radius);
    padding: 0.6rem 0.75rem; font: inherit; color: var(--text); }
  .share-row input:focus { outline: none; border-color: var(--accent); }
  .share-hint { font-size: var(--text-xs); color: var(--text-muted); margin-top: 0.45rem; }
  .shared-section { margin-top: 1.2rem; }
  .shared-section h2, .inbox h2 { font-size: var(--text-sm); color: var(--text-muted); font-weight: 600;
    margin: 0 0 0.5rem; }
  .badge { display: inline-block; border-radius: 999px; padding: 0.1rem 0.5rem; font-size: var(--text-xs);
    border: 1px solid var(--border); color: var(--text-muted); margin-left: 0.4rem; }
  .badge.analyzing { border-color: #f3c6c2; color: #a33; background: #fdeceb; }
  .badge.done { border-color: var(--border); background: var(--ok-bg); color: var(--ok); }
  @media (max-width: 640px) {
    body { padding: 1rem; }
    .share-row { flex-direction: column; }
    .share-row input, .share-row button { width: 100%; }
  }
  @media (min-width: 841px) {
    .share-row input { min-height: 2.6rem; }
  }
</style></head><body>
  <h1>TechRadar</h1>
  <div class="sub">Front row to new tech, filtered by your interests.</div>
  <div class="toolbar">
    <button id="fetchBtn" onclick="doFetch()">Fetch new items</button>
    <button onclick="location.href='/watch'" class="ghost" style="background:none;border:1px solid var(--border);color:var(--text-muted);font-size:var(--text-sm);">Watch &#9654;</button>
    <span class="stats" id="stats"></span>
  </div>
  <div id="fetchError"></div>
  <div class="share-box">
    <label for="shareUrl">Found something interesting anywhere? Drop it here (or use the phone&rsquo;s <em>Share &rarr; TechRadar</em>).</label>
    <div class="share-row">
      <input id="shareUrl" type="url" placeholder="https://youtube.com/watch?v=... or any page" enterkeyhint="send">
      <button id="shareBtn" onclick="doShare()">Share &amp; analyze</button>
    </div>
    <div class="share-hint" id="shareHint"></div>
  </div>
  <div class="shared-section" id="sharedWrap" hidden>
    <details open>
      <summary>Shared (inbox)</summary>
      <div id="sharedList"></div>
    </details>
  </div>
  <div id="dlStatus" class="dl-status"></div>
  <div id="items"></div>

<script>
function itemSharedHtml(it) {
  const status = it.fit_score == null
    ? '<span class="badge analyzing">analyzing…</span>'
    : '<span class="badge done">' + it.fit_score + '/10</span>';
  return `
    <div class="item" id="shared-${it.id}">
      <div class="item-top">
        <div class="title"><a href="${it.url}" target="_blank">${it.title}</a>${status}</div>
        <div class="score">${it.fit_score == null ? '—' : it.fit_score}<span class="score-unit">/10</span></div>
      </div>
      <div class="meta">shared${it.note ? ' · ' + it.note : ''}</div>
      <div class="reason">${it.reason && it.reason !== 'couldn&#39;t analyze this page (no transcript/text or LLM unavailable)' ? it.reason : (it.summary ? it.summary.slice(0, 200) : '')}</div>
    </div>
  `;
}

async function loadShared() {
  const r = await fetch('/api/shared');
  const data = await r.json();
  const el = document.getElementById('sharedList');
  const section = el.closest('.shared-section');
  if (data.items.length) {
    section.hidden = false;
    el.innerHTML = data.items.map(itemSharedHtml).join('');
  } else {
    section.hidden = true;
  }
}

async function doShare() {
  const inp = document.getElementById('shareUrl');
  const hint = document.getElementById('shareHint');
  const btn = document.getElementById('shareBtn');
  const url = inp.value.trim();
  if (!new RegExp('^https?:\\/\\/', 'i').test(url)) { hint.textContent = 'Paste a valid http(s) URL.'; return; }
  hint.textContent = '';
  btn.disabled = true; btn.textContent = 'Adding…';
  const body = new URLSearchParams({ url: url });
  const r = await fetch('/api/share', { method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: body.toString() });
  const j = await r.json();
  btn.disabled = false; btn.textContent = 'Share &amp; analyze';
  if (j.ok) {
    hint.textContent = 'Saved — analyzing now. It will appear in the inbox and the feed.';
    inp.value = '';
    load(); loadShared();
  } else {
    hint.textContent = j.reason || 'Failed to save share.';
  }
}

function itemHtml(it) {
  return `
    <div class="item ${it.seen ? 'seen' : ''}" id="item-${it.id}">
      <div class="item-top">
        <div class="title"><a href="${it.url}" target="_blank">${it.title}</a></div>
        <div class="score">${it.fit_score}<span class="score-unit">/10</span></div>
      </div>
      <div class="meta">${it.source}${it.published_at ? ' · ' + it.published_at : ''}</div>
      <div class="reason">${it.reason || ''}</div>
      <div class="row-actions">
        ${it.url && /youtube\.com|youtu\.be/.test(it.url) && !it.seen
          ? `<button class="ghost dl" onclick="startDl('${esc(it.url)}','mp4')">MP4</button>
             <button class="ghost dl" onclick="startDl('${esc(it.url)}','mp3')">MP3</button>` : ''}
        ${!it.seen ? `<button class="dismiss" onclick="markSeen(${it.id})">Dismiss</button>` : ''}
      </div>
    </div>
  `;
}
async function startDl(url, fmt) {
  const r = await fetch('/api/download', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({url, format: fmt})});
  const j = await r.json();
  const msg = document.getElementById('dlStatus');
  if (!msg) return;
  msg.textContent = j.ok ? `Downloading (${fmt})... see Downloads` : (j.reason||'failed');
}
}

async function load() {
  const r = await fetch('/api/items');
  const data = await r.json();
  const items = data.items;
  const newItems = items.filter(it => it.is_new && !it.seen);
  const oldItems = items.filter(it => !it.seen && !it.is_new);
  const seen = items.filter(it => it.seen);
  const el = document.getElementById('items');
  const group = (label, list) => '<section class="feed-group"><h3 class="group-label">' + label +
    '</h3>' + list.map(itemHtml).join('') + '</section>';
  el.innerHTML =
    (newItems.length ? group('New since you last looked', newItems) : '') +
    (oldItems.length ? group('Earlier', oldItems) : '') +
    (seen.length ? `
    <details class="seen-section">
      <summary>Dismissed (${seen.length})</summary>
      ${seen.map(itemHtml).join('')}
    </details>
  ` : '');
  const surfaced = items.length;
  const s = await fetch('/api/stats');
  const stats = await s.json();
  document.getElementById('stats').textContent =
    `${stats.total} tracked · ${stats.scored} scored · ${surfaced} surfaced`;
}

async function markSeen(id) {
  await fetch(`/api/items/${id}/seen`, { method: 'POST' });
  load();
}

async function doFetch() {
  const btn = document.getElementById('fetchBtn');
  const errEl = document.getElementById('fetchError');
  errEl.innerHTML = '';
  btn.disabled = true;
  btn.textContent = 'Fetching...';
  await fetch('/api/fetch', { method: 'POST' });
  const poll = setInterval(async () => {
    const r = await fetch('/api/fetch/status');
    const s = await r.json();
    if (!s.running) {
      clearInterval(poll);
      btn.disabled = false;
      btn.textContent = 'Fetch new items';
      if (s.error) {
        errEl.innerHTML = `<div class="fetch-error">Fetch failed: ${s.error}</div>`;
      }
      load();
    }
  }, 3000);
}

async function init() {
  await load();
  await loadShared();
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/service-worker.js').catch(() => {});
  }
}
init();
</script>
</body></html>"""


def create_app() -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        # Record "since last visit": stamp now every time the dashboard opens.
        conn = database.get_connection()
        database.set_meta(conn, "last_visit", datetime.now(timezone.utc).isoformat())
        conn.commit()
        conn.close()
        return PAGE

    @app.route("/api/items")
    def api_items():
        from techradar.ranking import rank_feed
        from techradar.config import load_sources

        interests = load_interests()
        sources = load_sources()
        ranking_cfg = sources.get("ranking", {})
        min_score = int(request.args.get("min_score", interests.get("min_score", 6)))
        limit = int(request.args.get("limit", ranking_cfg.get("limit", 200)))
        source_cap = int(request.args.get("cap", ranking_cfg.get("per_source_cap", 5)))
        half_life_days = float(ranking_cfg.get("half_life_days", 14))
        now_iso = datetime.now(timezone.utc).isoformat()

        conn = database.get_connection()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT rowid AS id, * FROM items "
            "ORDER BY discovered_at DESC LIMIT 20000",
        ).fetchall()
        last_visit = database.get_meta(conn, "last_visit", "")
        conn.close()

        items = [dict(r) for r in rows]
        ranked = rank_feed(items, min_score=min_score, limit=limit,
                           source_cap=source_cap, half_life_days=half_life_days)
        # Flag items discovered since the last page view so the front row
        # leads with what's genuinely new (the "since last visit" grouping).
        last_ts = None
        if last_visit:
            try:
                last_ts = datetime.fromisoformat(last_visit.replace("Z", "+00:00")).timestamp()
            except ValueError:
                last_ts = None
        for it in ranked:
            it["is_new"] = False
            if last_ts is not None and it.get("discovered_at"):
                try:
                    d = datetime.fromisoformat(str(it["discovered_at"]).replace("Z", "+00:00")).timestamp()
                    it["is_new"] = d > last_ts
                except ValueError:
                    pass
        return jsonify({"items": ranked, "now": now_iso, "ranking": ranking_cfg,
                        "last_visit": last_visit})

    @app.route("/api/items/<int:item_id>/seen", methods=["POST"])
    def api_mark_seen(item_id: int):
        conn = database.get_connection()
        conn.execute("UPDATE items SET seen = 1 WHERE rowid = ?", (item_id,))
        conn.commit()
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/stats")
    def api_stats():
        conn = database.get_connection()
        stats = database.get_stats(conn)
        conn.close()
        return jsonify(stats)
    @app.route("/api/download", methods=["POST"])
    def api_download():
        from techradar import downloader
        payload = request.get_json(silent=True) or {}
        url = str(payload.get("url", "")).strip()
        fmt = str(payload.get("format", "mp4")).strip().lower() or "mp4"
        if not url.startswith(("http://", "https://")):
            return jsonify({"ok": False, "reason": "bad url"}), 400
        height = int(payload.get("height", 720))
        state = downloader.download(url, fmt=fmt, height=height)
        return jsonify({"ok": True, "status": state["status"], "id": None})

    @app.route("/api/download/list")
    def api_download_list():
        from techradar import downloader
        return jsonify({"files": downloader.list_files()})

    @app.route("/api/download/media")
    def api_download_media():
        from techradar import downloader
        from flask import send_file as _send_file
        name = request.args.get("name", "")
        path = downloader.file_path(name)
        if not path:
            return jsonify({"ok": False, "reason": "not found"}), 404
        return _send_file(path, as_attachment=True, download_name=os.path.basename(path))
    

    @app.route("/api/fetch", methods=["POST"])
    def api_fetch():
        global _fetch_running, _fetch_error
        with _fetch_lock:
            if _fetch_running:
                return jsonify({"ok": False, "reason": "already running"}), 409
            _fetch_running = True
            _fetch_error = None
            threading.Thread(target=_run_fetch_background, daemon=True).start()
        return jsonify({"ok": True})

    @app.route("/api/fetch/status")
    def api_fetch_status():
        return jsonify({"running": _fetch_running, "error": _fetch_error})

    @app.route("/api/share", methods=["POST"])
    def api_share():
        """Share a URL into TechRadar. Accepts a form body (used by the PWA
        share target: fields url, title, text) or JSON {url, title}."""
        from techradar import database

        if request.content_type and "json" in request.content_type:
            payload = request.get_json(silent=True) or {}
            url = str(payload.get("url", "")).strip()
            title = str(payload.get("title", ""))[:300].strip()
        else:
            url = str(request.form.get("url", "")).strip()
            title = str(request.form.get("title", request.form.get("text", "")))[:300].strip()

        if not url.startswith(("http://", "https://")):
            return jsonify({"ok": False, "reason": "URL must start with http(s)://"}), 400

        conn = database.get_connection()
        if database.item_exists(conn, url):
            conn.close()
            return jsonify({"ok": False, "reason": "already tracked"}), 409
        added = database.store_shared(conn, url, title)
        conn.close()
        if not added:
            return jsonify({"ok": False, "reason": "already tracked"}), 409

        if os.environ.get("SHARE_ANALYZE_ON_SHARE", "1") != "0":
            start_analysis(url, title)
        return jsonify({"ok": True})

    @app.route("/share")
    def share_landing():
        """Bookmarklet / iOS-friendly GET share: /share?url=...&title=..."""
        from techradar import database

        url = request.args.get("url", "").strip()
        title = request.args.get("title", "").strip()
        if not url.startswith(("http://", "https://")):
            return "Missing or invalid ?url= (http(s) required).", 400
        conn = database.get_connection()
        added = database.store_shared(conn, url, title)
        conn.close()
        if added:
            if os.environ.get("SHARE_ANALYZE_ON_SHARE", "1") != "0":
                start_analysis(url, title)
            msg = "Saved to TechRadar &amp; analysis started."
        else:
            msg = "Already in TechRadar."
        return f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>TechRadar</title></head>" \
            f"<body style='font-family:system-ui;padding:2rem'><h1>{msg}</h1><p><a href='/' style='color:#3b5bfd'>← back to the feed</a></p></body></html>"

    @app.route("/api/shared")
    def api_shared():
        conn = database.get_connection()
        rows = database.get_shared_items(conn)
        conn.close()
        return jsonify({"items": [dict(r) for r in rows]})

    @app.route("/manifest.webmanifest")
    def manifest():
        return jsonify({
            "name": "TechRadar",
            "short_name": "TechRadar",
            "start_url": "/",
            "display": "standalone",
            "background_color": "#ffffff",
            "theme_color": "#3b5bfd",
            "icons": [{"src": "/static_techradar-icon.svg", "sizes": "any", "type": "image/svg+xml"}],
            "share_target": {
                "action": "/api/share",
                "method": "POST",
                "enctype": "multipart/form-data",
                "params": {"title": "title", "text": "text", "url": "url"},
            },
        })

    @app.route("/service-worker.js")
    def service_worker():
        sw = """self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));
self.addEventListener('fetch', (e) => {
  // Network-first with cache fallback for GET navigation.
  if (e.request.method === 'GET' && e.request.mode === 'navigate') {
    e.respondWith(fetch(e.request).then((r) => { const c = r.clone(); caches.open('techradar-v1').then((cache) => cache.put(e.request, c)); return r; })
      .catch(() => caches.match(e.request).then((r) => r || caches.match('/'))));
    return;
  }
});"""
        from flask import Response
        return Response(sw, mimetype="application/javascript")

    @app.route("/static_techradar-icon.svg")
    def techradar_icon():
        from flask import Response
        svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' "
               "height='100' rx='20' fill='#3b5bfd'/><text x='50' y='70' font-size='56' "
               "text-anchor='middle' fill='white' font-family='system-ui' font-weight='700'>T</text></svg>")
        return Response(svg, mimetype="image/svg+xml")


    @app.route("/watch")
    def watch_page():
        return WATCH_PAGE

    @app.route("/api/watch/feed")
    def api_watch_feed():
        from techradar import watch as wm
        try:
            return jsonify({"items": wm.recent_feed(limit=40)})
        except Exception as e:
            log.warning("watch feed failed: %s", e)
            return jsonify({"items": [], "error": str(e)})

    @app.route("/api/watch/suggestions")
    def api_watch_suggestions():
        from techradar import watch as wm
        try:
            return jsonify({"items": wm.suggestions(limit=12)})
        except Exception as e:
            log.warning("watch suggestions failed: %s", e)
            return jsonify({"items": [], "error": str(e)})

    @app.route("/api/watch/stream")
    def api_watch_stream():
        from techradar import watch as wm
        url = request.args.get("url", "")
        if not url.startswith(("http://", "https://")):
            return jsonify({"ok": False, "reason": "invalid url"}), 400
        try:
            info = wm.extract_stream(url)
            token = _secrets.token_hex(8)
            _proxy_tokens[token] = {"url": info["url"], "headers": info.get("http_headers") or {},
                                    "ts": _time.time()}
            proxy_url = "/api/watch/proxy?t=" + token
            return jsonify({"ok": True, "url": proxy_url, "direct": info["url"],
                            "title": info["title"], "channel": info["channel"],
                            "thumbnail": info["thumbnail"], "video_id": info["video_id"]})
        except Exception as e:
            log.warning("stream extract failed: %s", e)
            return jsonify({"ok": False, "reason": "couldn't extract stream: " + str(e)[:120]})

    @app.route("/api/watch/watched", methods=["POST"])
    def api_watch_watched():
        from techradar import database as dbmod, watch
        payload = request.get_json(silent=True) or {}
        vid = str(payload.get("video_id", "")).strip() or (watch.video_id(payload.get("url", "")) or "")
        if not vid:
            return jsonify({"ok": False, "reason": "no video_id"}), 400
        conn = dbmod.get_connection()
        dbmod.store_watched(conn, vid, payload.get("url", ""), payload.get("title", ""),
                            payload.get("channel", ""), payload.get("channel_id", ""),
                            float(payload.get("progress") or 0))
        conn.close()
        return jsonify({"ok": True})

    @app.route("/api/watch/proxy")
    def api_watch_proxy():
        """Range-aware reverse proxy for the direct YouTube stream URL. Sends
        proper browser headers (UA/Referer) and forwards the client's Range so
        long videos play + seek reliably instead of being 403'd/throttled by
        the CDN on raw direct URLs."""
        import httpx
        from flask import Response, stream_with_context

        token = request.args.get("t", "")
        entry = _proxy_tokens.get(token)
        if not entry:
            return jsonify({"ok": False, "reason": "stream token expired; re-open the video"}), 410
        src = entry["url"]
        if not src.startswith("http"):
            return jsonify({"ok": False, "reason": "bad src"}), 400
        headers = dict(entry["headers"])  # yt-dlp's exact extraction headers (nsig-bound)
        headers.setdefault("Accept-Language", "en-US,en;q=0.9")
        rng = request.headers.get("Range", "").strip()
        # YouTube's CDN 403s open-ended/no-Range requests -> always fetch a
        # BOUNDED range upstream; Range-less clients get the first chunk as a
        # plain 200 and then seek via Range.
        INITIAL = 8 * 1024 * 1024
        if rng.startswith("bytes=") and rng != "bytes=0-":
            headers["Range"] = rng
            forced_200 = False
        else:
            headers["Range"] = f"bytes=0-{INITIAL - 1}"
            forced_200 = (rng == "")  # true when the client sent no Range at all
        try:
            up = httpx.get(src, headers=headers, timeout=None, follow_redirects=True)
        except Exception as e:
            log.warning("proxy upstream failed: %s", e)
            return jsonify({"ok": False, "reason": "upstream error: " + str(e)[:100]}), 502
        rh = {
            "Content-Type": up.headers.get("Content-Type", "video/mp4"),
            "Accept-Ranges": "bytes",
        }
        if up.headers.get("Content-Length"):
            rh["Content-Length"] = up.headers["Content-Length"]
        if forced_200:
            status = 200  # initial chunk only; browser will Range-request the rest
        else:
            status = up.status_code
            if up.headers.get("Content-Range"):
                rh["Content-Range"] = up.headers["Content-Range"]

        def gen():
            try:
                for chunk in up.iter_bytes(65536):
                    yield chunk
            finally:
                up.close()

        return Response(stream_with_context(gen()), status=status, headers=rh)

    @app.route("/api/watch/play", methods=["POST"])
    def api_watch_play():
        from techradar import watch as wm
        payload = request.get_json(silent=True) or {}
        url = str(payload.get("url", "")).strip()
        vid = str(payload.get("video_id", "")).strip() or (wm.video_id(url) or "")
        if not url.startswith("http") or not vid:
            return jsonify({"ok": False, "reason": "url+video_id required"}), 400
        wm.download_for_play(url, vid)
        return jsonify({"ok": True, "video_id": vid})

    @app.route("/api/watch/play/status/<video_id>")
    def api_watch_play_status(video_id: str):
        from techradar import watch as wm
        st = wm.dl_status(video_id)
        media = "/api/watch/media/" + video_id if st.get("path") else None
        return jsonify({"status": st.get("status"), "pct": round(st.get("pct", 0) * 100),
                        "err": st.get("err"), "media": media})

    @app.route("/api/watch/media/<video_id>")
    def api_watch_media(video_id: str):
        from techradar import watch as wm
        from flask import send_file
        path = wm.media_ready(video_id)
        if not path:
            return jsonify({"ok": False, "reason": "not downloaded yet"}), 404
        return send_file(path, mimetype="video/mp4", conditional=True)

    return app
