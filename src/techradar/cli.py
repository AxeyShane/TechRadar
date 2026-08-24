import logging

import typer

app = typer.Typer(help="TechRadar -- personal front row to new technology.")

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


@app.command()
def fetch(limit: int = typer.Option(None, help="Max new items to score this run")):
    """Fetch all sources, score against your interests, store new items."""
    from techradar.pipeline import run
    stats = run(limit_new=limit)
    typer.echo(f"Fetched {stats['fetched']} | new {stats['new']} | scored {stats['scored']}")


@app.command()
def web(port: int = 8766, host: str = "127.0.0.1"):
    """Launch the dashboard. Pass --host 0.0.0.0 to reach it from your phone on the same network."""
    from techradar.webui import create_app
    create_app().run(host=host, port=port, debug=False)


@app.command()
def backfill(channel: str, limit: int = typer.Option(None, help="Cap how many videos to process this run")):
    """Catch up on a YouTube channel's full history (not just the last ~15
    the live feed holds). CHANNEL can be a name from sources.yaml's feeds
    list, a channel_id, a @handle, or a full URL."""
    from techradar import backfill as backfill_mod
    stats = backfill_mod.run(channel, limit=limit)
    typer.echo(f"Found {stats['found']} | new {stats['new']} | scored {stats['scored']}")


@app.command()
def review_profile():
    """Look at what you've dismissed and propose discrete learned notes
    (e.g. "exclude funding-round posts"). Inserted into the DB as
    status=proposed -- never touches interests.yaml or affects scoring
    until you `techradar notes-approve <id>` each one."""
    from techradar import database
    from techradar.config import load_interests
    from techradar.recommender import gather_dismissed, gather_shared, gather_watched, propose_notes

    profile = load_interests().get("profile", "")
    conn = database.get_connection()
    dismissed = gather_dismissed(conn)
    shared = gather_shared(conn)
    watched = gather_watched(conn)
    existing_notes = database.get_approved_notes(conn)

    if not dismissed and not shared and not watched:
        typer.echo("No dismissed, shared, or watched items yet -- nothing to learn from.")
        conn.close()
        return

    typer.echo(f"Reviewing {len(dismissed)} dismissed + {len(shared)} shared + {len(watched)} watched item(s)...")
    notes = propose_notes(profile, dismissed, existing_notes, shared=shared, watched=watched)
    if not notes:
        typer.echo("No new notes proposed (either nothing new to learn, or the LLM call failed -- check logs).")
        conn.close()
        return

    for note in notes:
        evidence = "; ".join(note.get("evidence_titles", []))
        note_id = database.add_note(conn, note.get("kind", "exclude"), note.get("text", ""), evidence)
        typer.echo(f"{note_id}: [{note.get('kind')}] {note.get('text')}")

    conn.close()
    typer.echo(f"\n{len(notes)} note(s) proposed. Review with `techradar notes-list --status proposed`, "
               f"then `techradar notes-approve <id>` or `notes-reject <id>`.")


@app.command()
def notes_list(status: str = typer.Option(None, help="Filter: proposed | approved | rejected")):
    """List learned notes."""
    from techradar import database
    conn = database.get_connection()
    notes = database.list_notes(conn, status=status)
    conn.close()

    if not notes:
        typer.echo("No notes." if not status else f"No {status} notes.")
        return
    for n in notes:
        typer.echo(f"{n['id']}: [{n['status']}] [{n['kind']}] {n['text']}")
        if n["evidence"]:
            typer.echo(f"    evidence: {n['evidence']}")


@app.command()
def notes_approve(note_id: int):
    """Approve a proposed note -- it starts affecting scoring immediately."""
    from techradar import database
    conn = database.get_connection()
    database.set_note_status(conn, note_id, "approved")
    conn.close()
    typer.echo(f"Approved note {note_id}.")


@app.command()
def notes_reject(note_id: int):
    """Reject a proposed note -- it's kept for the record but never used."""
    from techradar import database
    conn = database.get_connection()
    database.set_note_status(conn, note_id, "rejected")
    conn.close()
    typer.echo(f"Rejected note {note_id}.")



@app.command()
def sweep(topic: str = typer.Option(None, help="Sweep a single topic; if omitted, uses config/sources.yaml discovery.topics"),
          days: int = typer.Option(7, help="Look back this many days"),
          limit: int = typer.Option(10, help="Max items to keep from the sweep"),
          provider: str = typer.Option(None, help="llm (default) | mixedbread (TOAST-1)"),
          dry_run: bool = typer.Option(False, help="Only show the queries you would run -- no search, no cost")):
    """Proactive discovery sweep: go find NEW items on your topics, beyond
    your subscribed feeds. Requires an LLM (OpenRouter/local) for provider=llm,
    or MIXEDBREAD_API_KEY for provider=mixedbread. Sweep results are scored and
    stored exactly like feed items."""
    from techradar.sources import discovery

    topics = [topic] if topic else None
    if dry_run:
        candidates = discovery.sweep(topics=topics, days=days, provider=provider,
                                     max_items=limit, dry_run=True)
        typer.echo(f"(dry-run) planned work for {len(topics) if topics else 'configured'} topic(s).")
        return

    candidates = discovery.sweep(topics=topics, days=days, provider=provider, max_items=limit)
    if not candidates:
        typer.echo("Sweep returned no candidates (check topics, keys, network -- see logs).")
        return

    from techradar import database, pipeline
    conn = database.get_connection()
    new_items = pipeline.dedupe_new(conn, candidates)
    scored = pipeline.score_and_store(conn, new_items, load_interests().get("profile", ""))
    conn.close()
    typer.echo(f"Sweep: {len(candidates)} candidates | {len(new_items)} new | {scored} scored")


@app.command()
def share(url: str, title: str = typer.Option("", help="Optional title hint"),
          analyze: bool = typer.Option(True, help="Analyze it now (transcript/summary + score)")):
    """Share a URL into TechRadar from the CLI: it lands in the inbox,
    gets analyzed (YouTube: captions then local transcription; else page
    extraction), scored, and appears on the dashboard."""
    from techradar import database
    from techradar import enrich

    conn = database.get_connection()
    if database.item_exists(conn, url):
        typer.echo("Already tracked.")
        conn.close()
        return
    added = database.store_shared(conn, url, title)
    conn.close()
    if not added:
        typer.echo("Already in TechRadar.")
        return
    typer.echo("Added to inbox.")
    if analyze:
        item = enrich.analyze_url(url, title)
        conn = database.get_connection()
        database.update_item_after_analysis(conn, url, item)
        conn.close()
        score = item.get("fit_score")
        typer.echo(f"Analyzed: {item['title'][:60]}")
        typer.echo(f"  score: {score if score is not None else 'n/a'} -- reason: {item.get('reason', '')}")


@app.command()
def transcribe(url: str = typer.Option(None, help="Video/audio URL (yt-dlp) to transcribe"),
               path: str = typer.Option(None, help="Local audio/video file to transcribe"),
               model: str = typer.Option(None, help="faster-whisper model (default: WHISPER_MODEL env or medium)"),
               srt: bool = typer.Option(False, help="Also print the transcript as SRT subtitles"),
               summary: bool = typer.Option(False, help="Print an LLM summary (OpenRouter/local) instead of raw text")):
    """Transcribe a video/audio URL or file locally (faster-whisper on your
    GPU/CPU) and cache it in SQLite. Requires: uv pip install -e '.[transcribe]'"""
    from techradar import transcriber

    if not url and not path:
        typer.echo("Provide --url or --path.")
        raise typer.Exit(1)
    model = model or transcriber.DEFAULT_MODEL
    result = transcriber.transcribe(url=url, path=path, model=model)
    typer.echo(f"language={result['language']} | segments={len(result['segments'])} | chars={len(result['text'])}")
    if summary:
        text = result["text"]
        from techradar.summarizer import summarize_transcript
        typer.echo("--- summary ---")
        typer.echo(summarize_transcript(text))
    elif srt:
        typer.echo("--- SRT ---")
        typer.echo(transcriber.segments_to_srt(result["segments"]))
    else:
        typer.echo(result["text"][:4000])


@app.command()
def patents(keyword: str = typer.Option(None, help="Watch a single keyword/domain; else uses config patents.keywords"),
            days: int = typer.Option(30, help="Look back this many days for newly-published patents"),
            limit: int = typer.Option(10, help="Max items to keep"),
            dry_run: bool = typer.Option(False, help="Only show the keywords you would watch -- no network")):
    """Surface newly-published patents in your domains (ahead of the videos).
    Queries an authoritative patent index (Google Patents: US/EP/WIPO/CN),
    filters to recent, and curates+ranks via your LLM (OpenRouter/local).
    Results are scored and stored like every other feed item."""
    from techradar import database, pipeline
    from techradar import patents as patents_mod
    from techradar.config import load_interests

    keys = [keyword] if keyword else None
    if dry_run:
        patents_mod.run(domains=keys, days=days, max_items=limit, dry_run=True)
        typer.echo("(dry-run) no network calls made.")
        return
    candidates = patents_mod.run(domains=keys, days=days, max_items=limit)
    if not candidates:
        typer.echo("Patent watch returned no recent matches (see logs). It can take a few "
                   "minutes for a filing to appear in the public index; try again daily.")
        return
    conn = database.get_connection()
    new_items = pipeline.dedupe_new(conn, candidates)
    scored = pipeline.score_and_store(conn, new_items, load_interests().get("profile", ""))
    conn.close()
    typer.echo(f"Patents: {len(candidates)} found | {len(new_items)} new | {scored} scored")

if __name__ == "__main__":
    app()
