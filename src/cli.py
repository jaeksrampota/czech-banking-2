import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.table import Table

from src.models.database import Database

# Force UTF-8 output on Windows to handle Czech characters
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

console = Console(force_terminal=True)

# Resolve project root (where pyproject.toml lives)
PROJECT_ROOT = Path(__file__).parent.parent


def _setup_logging(level: str = "INFO"):
    log_dir = PROJECT_ROOT / "data"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "ci_monitor.log", encoding="utf-8"),
        ],
    )


def _db_path(config_dir: str) -> str:
    """Database path from settings.yaml (relative paths resolve against the project root)."""
    settings_path = Path(config_dir) / "settings.yaml"
    if settings_path.exists():
        settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        db_path = settings.get("database", {}).get("path", "data/db/ci_monitor.sqlite")
    else:
        db_path = "data/db/ci_monitor.sqlite"

    # Make path relative to project root
    if not os.path.isabs(db_path):
        db_path = str(PROJECT_ROOT / db_path)
    return db_path


def _get_db(config_dir: str) -> Database:
    return Database(_db_path(config_dir))


def _parse_since(since: str) -> str:
    units = {"d": "days", "h": "hours", "w": "weeks"}
    if since[-1] in units:
        delta = timedelta(**{units[since[-1]]: int(since[:-1])})
        now = datetime.now(UTC).replace(tzinfo=None)
        return (now - delta).isoformat(timespec="seconds")
    return since  # assume ISO date


@click.group()
@click.option("--config-dir", default=None, help="Config directory path")
@click.option("--verbose", "-v", is_flag=True, help="Verbose logging")
@click.pass_context
def cli(ctx, config_dir, verbose):
    """Czech Banking Competitive Intelligence Monitor"""
    ctx.ensure_object(dict)
    if config_dir is None:
        config_dir = str(PROJECT_ROOT / "config")
    ctx.obj["config_dir"] = config_dir
    _setup_logging("DEBUG" if verbose else "INFO")


@cli.command("init-db")
@click.pass_context
def init_db(ctx):
    """Inicializuje databázi a načte segmenty i společnosti z configu."""
    config_dir = ctx.obj["config_dir"]
    db = _get_db(config_dir)
    db.initialize()
    db.seed_segments(config_dir)
    db.seed_competitors(config_dir)

    segmenty = db.get_segmenty()
    linie = db.get_produktove_linie()
    competitors = db.get_competitors()

    seg_table = Table(title="Segmenty")
    seg_table.add_column("ID", style="cyan")
    seg_table.add_column("Název", style="bold")
    seg_table.add_column("Produktové linie", style="dim")
    for s in segmenty:
        linie_nazvy = [linie_row["nazev"] for linie_row in linie if linie_row["segment_id"] == s["id"]]
        seg_table.add_row(s["id"], s["nazev"], ", ".join(linie_nazvy))
    console.print(seg_table)

    comp_table = Table(title=f"Společnosti ({len(competitors)})")
    comp_table.add_column("ID", style="cyan")
    comp_table.add_column("Název", style="bold")
    comp_table.add_column("Tier")
    comp_table.add_column("IČO")
    for c in competitors:
        comp_table.add_row(c["id"], c["name"], str(c["tier"]), c.get("ico") or "—")
    console.print(comp_table)

    console.print(
        f"[green]Databáze inicializována: {len(segmenty)} segmentů, "
        f"{len(linie)} produktových linií, {len(competitors)} společností.[/green]"
    )
    db.close()


@cli.command()
@click.option("--source", "-s", type=click.Choice(["ares", "jobs", "news", "website", "all"]), default="all")
@click.option("--competitor", "-c", default="all", help="Competitor ID or 'all'")
@click.pass_context
def collect(ctx, source, competitor):
    """Run data collectors."""
    config_dir = ctx.obj["config_dir"]
    db = _get_db(config_dir)
    db.initialize()

    competitor_ids = None
    if competitor != "all":
        competitor_ids = [competitor]

    collectors_to_run = []

    if source in ("ares", "all"):
        from src.collectors.ares import AresCollector
        collectors_to_run.append(AresCollector(db, config_dir))

    if source in ("jobs", "all"):
        from src.collectors.job_postings import JobPostingsCollector
        collectors_to_run.append(JobPostingsCollector(db, config_dir))

    if source in ("news", "all"):
        from src.collectors.news import NewsCollector
        collectors_to_run.append(NewsCollector(db, config_dir))

    if source in ("website", "all"):
        from src.collectors.website import WebsiteCollector
        collectors_to_run.append(WebsiteCollector(db, config_dir))

    total_signals = 0
    for collector in collectors_to_run:
        console.print(f"\n[bold]Running {collector.name} collector...[/bold]")
        with collector:
            results = collector.run(competitor_ids)

        table = Table(title=f"{collector.name} Results")
        table.add_column("Competitor", style="cyan")
        table.add_column("Status")
        table.add_column("Signals", justify="right")

        for cid, info in results.get("competitors", {}).items():
            status_style = "green" if info["status"] == "success" else "red"
            signals = str(info.get("signals", 0)) if info["status"] == "success" else info.get("error", "error")[:50]
            table.add_row(cid, f"[{status_style}]{info['status']}[/{status_style}]", signals)

        console.print(table)
        total_signals += results.get("new_signals", 0)

    console.print(f"\n[bold green]Done. {total_signals} new signals collected.[/bold green]")
    db.close()


@cli.command()
@click.option("--competitor", "-c", default=None, help="Filter by competitor ID")
@click.option("--source", "-s", default=None, help="Filter by source")
@click.option("--severity", default=None, type=int, help="Minimum severity (1-5)")
@click.option("--since", default="7d", help="Time window (e.g. 7d, 24h, 4w)")
@click.option("--limit", "-n", default=50, help="Max results")
@click.pass_context
def signals(ctx, competitor, source, severity, since, limit):
    """View collected signals."""
    config_dir = ctx.obj["config_dir"]
    db = _get_db(config_dir)

    since_dt = _parse_since(since) if since else None
    rows = db.get_signals(
        competitor_id=competitor,
        source=source,
        min_severity=severity,
        since=since_dt,
        limit=limit,
    )

    if not rows:
        console.print("[yellow]No signals found matching criteria.[/yellow]")
        db.close()
        return

    table = Table(title=f"Signals ({len(rows)} results)")
    table.add_column("Time", style="dim", max_width=16)
    table.add_column("Competitor", style="cyan", max_width=20)
    table.add_column("Source", max_width=10)
    table.add_column("Type", max_width=15)
    table.add_column("Title", max_width=50)
    table.add_column("Sev", justify="center", max_width=3)

    severity_colors = {1: "green", 2: "blue", 3: "yellow", 4: "red", 5: "bold red"}

    for sig in rows:
        sev = sig["severity"]
        sev_color = severity_colors.get(sev, "white")
        time_str = sig["detected_at"][:16].replace("T", " ")
        table.add_row(
            time_str,
            sig["competitor_id"],
            sig["source"],
            sig["signal_type"],
            sig["title"][:50],
            f"[{sev_color}]{sev}[/{sev_color}]",
        )

    console.print(table)
    db.close()


@cli.command()
@click.pass_context
def status(ctx):
    """Show collector run status."""
    config_dir = ctx.obj["config_dir"]
    db = _get_db(config_dir)

    runs = db.get_collector_status()
    if not runs:
        console.print("[yellow]No collector runs found.[/yellow]")
        db.close()
        return

    table = Table(title="Recent Collector Runs")
    table.add_column("Collector", style="bold")
    table.add_column("Competitor", style="cyan")
    table.add_column("Started", style="dim")
    table.add_column("Status")
    table.add_column("Signals", justify="right")
    table.add_column("Error", max_width=40)

    for run in runs:
        status_style = "green" if run["status"] == "success" else "red"
        table.add_row(
            run["collector_name"],
            run.get("competitor_id", "all"),
            run["started_at"][:16].replace("T", " "),
            f"[{status_style}]{run['status']}[/{status_style}]",
            str(run.get("signals_found", 0)),
            run.get("error_message", "")[:40] if run.get("error_message") else "",
        )

    console.print(table)
    db.close()


@cli.command()
@click.pass_context
def competitors(ctx):
    """List monitored competitors and their configured sources."""
    config_dir = ctx.obj["config_dir"]
    db = _get_db(config_dir)

    table = Table(title="Monitored Competitors")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Tier")
    table.add_column("IČO")
    table.add_column("Sources", style="dim")

    for comp in db.get_competitors():
        # Load config to show sources
        config_path = comp.get("config_path")
        sources_str = ""
        if config_path and Path(config_path).exists():
            cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
            source_keys = list(cfg.get("sources", {}).keys())
            sources_str = ", ".join(source_keys)

        table.add_row(
            comp["id"],
            comp["name"],
            str(comp["tier"]),
            comp.get("ico", "—"),
            sources_str,
        )

    console.print(table)
    db.close()


@cli.command()
@click.option("--output", "-o", default=None, help="Output file path (.xlsx)")
@click.pass_context
def export(ctx, output):
    """Export all data to Excel (.xlsx) file."""
    config_dir = ctx.obj["config_dir"]
    db = _get_db(config_dir)

    from src.export import export_to_xlsx
    path = export_to_xlsx(db, output)
    console.print(f"[bold green]Exported to: {path}[/bold green]")
    db.close()


@cli.command()
@click.option("--segment", "-s", default=None, help="Slug segmentu (ucty/hypoteky/investice), volitelné")
@click.option("--since", default="30d", help="Časové okno (např. 30d, 90d)")
@click.pass_context
def articlize(ctx, segment, since):
    """Převede existující news signály na články v redakční vrstvě (idempotentní)."""
    config_dir = ctx.obj["config_dir"]
    db = _get_db(config_dir)

    since_iso = _parse_since(since)
    segment_id = None
    if segment:
        seg = db.get_segment(segment)
        if not seg:
            console.print(f"[red]Segment '{segment}' nenalezen.[/red]")
            db.close()
            return
        segment_id = seg["id"]

    # Vezmi všechny news signály v okně
    rows = db.get_signals(source="news", since=since_iso, limit=0)
    created = 0
    skipped = 0
    for sig in rows:
        ok = db.insert_clanek_from_signal(sig, segment_id=segment_id)
        if ok:
            created += 1
        else:
            skipped += 1

    console.print(
        f"[bold green]Vytvořeno {created} článků[/bold green], "
        f"přeskočeno {skipped} (již existují).",
    )
    db.close()


@cli.command()
@click.pass_context
def schedule(ctx):
    """Run collectors on the schedule declared in settings.yaml."""
    config_dir = ctx.obj["config_dir"]
    settings_path = Path(config_dir) / "settings.yaml"
    if settings_path.exists():
        settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        db_path = settings.get("database", {}).get("path", "data/db/ci_monitor.sqlite")
    else:
        db_path = "data/db/ci_monitor.sqlite"
    if not os.path.isabs(db_path):
        db_path = str(PROJECT_ROOT / db_path)

    Database(db_path).initialize()  # ensure schema exists before first tick

    from src.scheduler import build_scheduler
    scheduler = build_scheduler(db_path, config_dir)
    jobs = scheduler.get_jobs()
    if not jobs:
        console.print("[yellow]No schedules configured in settings.yaml.[/yellow]")
        return

    table = Table(title="Scheduled Jobs")
    table.add_column("Job", style="bold")
    table.add_column("Next run", style="dim")
    for job in jobs:
        table.add_row(job.id, str(job.trigger))
    console.print(table)
    console.print("[green]Scheduler running. Ctrl+C to stop.[/green]")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)
        console.print("[yellow]Scheduler stopped.[/yellow]")


@cli.command()
@click.option("--port", "-p", default=5000, help="Port to serve on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.pass_context
def dashboard(ctx, port, host):
    """Start the dashboard web server."""
    config_dir = ctx.obj["config_dir"]
    settings_path = Path(config_dir) / "settings.yaml"

    if settings_path.exists():
        settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        db_path = settings.get("database", {}).get("path", "data/db/ci_monitor.sqlite")
    else:
        db_path = "data/db/ci_monitor.sqlite"

    if not os.path.isabs(db_path):
        db_path = str(PROJECT_ROOT / db_path)

    from src.api import DASHBOARD_DIST, create_app
    app = create_app(db_path)

    if not DASHBOARD_DIST.exists():
        console.print("[yellow]Dashboard not built. Building now...[/yellow]")
        dashboard_dir = PROJECT_ROOT / "dashboard"
        if not (dashboard_dir / "node_modules").exists():
            console.print("[dim]Installing npm dependencies...[/dim]")
            os.system(f'cd "{dashboard_dir}" && npm install')
        console.print("[dim]Building dashboard...[/dim]")
        ret = os.system(f'cd "{dashboard_dir}" && npm run build')
        if ret != 0:
            console.print("[red]Dashboard build failed. Install Node.js and run:[/red]")
            console.print("[dim]  cd dashboard && npm install && npm run build[/dim]")
            return

    console.print("\n[bold]CI Monitor Dashboard[/bold]")
    console.print(f"  [dim]API:[/dim]       http://{host}:{port}/api/summary")
    console.print(f"  [dim]Dashboard:[/dim]  http://{host}:{port}/")
    console.print(f"  [dim]Database:[/dim]   {db_path}\n")

    app.run(host=host, port=port, debug=False)


# ── FINeCIM ──────────────────────────────────────────────────────

_FINECIM_TABLES = (
    ("finecim_subjekty", "Subjekty"),
    ("spolecnost_detail", "Profily společností"),
    ("clanky", "Články"),
    ("kampane", "Kampaně"),
    ("kampane_kreativy", "Kreativy kampaní"),
    ("mystery_shopping", "Mystery shopping"),
    ("produkty", "Produkty"),
    ("executive_summary", "Executive summary"),
    ("executive_summary_polozky", "Položky executive summary"),
    ("finecim_prilohy", "Přílohy"),
    ("finecim_vazby", "Vazby na společnosti"),
)
_FINECIM_ID_TABLES = ("clanky", "kampane", "mystery_shopping", "produkty", "executive_summary")


def _finecim_fail(message: str) -> None:
    """Print a clear error (no traceback) and exit with code 1."""
    console.print(message, style="red", markup=False)
    raise SystemExit(1)


def _finecim_credentials():
    from src.finecim.credentials import CredentialsError, load_credentials

    try:
        return load_credentials()
    except CredentialsError as exc:
        _finecim_fail(
            f"{exc}\nSee .env.example and finecim-research/SCRAPER.md for how to configure them."
        )


def _make_finecim_client(config_dir: str, credentials):
    """Factory for the FINeCIM client (module-level so tests can replace it)."""
    from src.finecim.sync import client_from_settings

    return client_from_settings(config_dir, credentials)


def _mask(value: str) -> str:
    return (value[:2] + "***") if len(value) > 2 else "***"


@cli.group()
def finecim():
    """FINeCIM (www.finecim.cz) scraper: login check, sync, status."""


@finecim.command("login-check")
@click.pass_context
def finecim_login_check(ctx):
    """Load credentials, log in and persist the session cookies."""
    from src.finecim.client import FinecimAuthError, FinecimHTTPError

    config_dir = ctx.obj["config_dir"]
    creds = _finecim_credentials()
    console.print(f"Credentials from: {creds.source} (user {_mask(creds.username)})", markup=False)
    try:
        with _make_finecim_client(config_dir, creds) as client:
            client.login()
            ok = client.is_logged_in()
    except (FinecimAuthError, FinecimHTTPError) as exc:
        _finecim_fail(f"FINeCIM login failed: {exc}")
    if not ok:
        _finecim_fail("FINeCIM login failed: the session is not signed in after login.")
    console.print("[green]FINeCIM login OK; session cookies saved.[/green]")


@finecim.command("sync")
@click.option("--entity", "-e", "entities", multiple=True,
              type=click.Choice(["all", "taxonomy", "company", "news", "campaign", "mystery", "product",
                                 "summary"]),
              help="Entity to sync (repeatable; default all). 'taxonomy' alone refreshes only the "
                   "segments and the /subjekty company lists (the taxonomy always runs first).")
@click.option("--segment", "-s", "segments", multiple=True,
              help="FINeCIM segment slug (repeatable; default all).")
@click.option("--max-pages", type=click.IntRange(min=1), default=None,
              help="Page budget per entity and segment, head scan and backfill together; only "
                   "pages on which a detail was fetched count (default 3; unlimited with --full).")
@click.option("--max-items", type=click.IntRange(min=1), default=None,
              help="Item budget: max detail fetches per entity and segment (default 120 for "
                   "news, campaigns, mystery shopping and products; unlimited with --full).")
@click.option("--years", "years", multiple=True, type=int,
              help="Executive summaries: refetch every stored month of this year (repeatable).")
@click.option("--full", is_flag=True,
              help="No early stop and no page budget: walk every list page; refetch every company "
                   "profile.")
@click.option("--all-companies", is_flag=True, help="Fetch profiles of every subject, not only mapped ones.")
@click.option("--dry-run", is_flag=True,
              help="Validate the options and print the plan; no credentials, no network, no writes.")
@click.pass_context
def finecim_sync(ctx, entities, segments, max_pages, max_items, years, full, all_companies, dry_run):
    """Incrementally sync FINeCIM content into the database.

    Each run spends at most --max-pages list pages (pages with a detail fetch) and
    --max-items detail fetches per entity and segment: new items from page 1 first, then
    the backfill of older pages continues where the last run stopped."""
    from src.finecim.client import FinecimAuthError, FinecimHTTPError
    from src.finecim.sync import DEFAULT_MAX_PAGES, ENTITIES, FinecimSync

    config_dir = ctx.obj["config_dir"]
    if not entities or "all" in entities:
        wanted = list(ENTITIES)
    elif set(entities) == {"taxonomy"}:
        wanted = ["taxonomy"]
    else:
        wanted = [e for e in ENTITIES if e in entities]

    if dry_run:
        _finecim_dry_run(config_dir, wanted, list(segments), max_pages, max_items, full, all_companies,
                         years=list(years))
        return

    # validate the segments against the config before asking for credentials or logging in
    try:
        FinecimSync(None, None, config_dir)._resolve_segments(list(segments) or None)
    except ValueError as exc:
        _finecim_fail(str(exc))
    creds = _finecim_credentials()

    db = _get_db(config_dir)
    try:
        db.initialize()
        with _make_finecim_client(config_dir, creds) as client:
            syncer = FinecimSync(client, db, config_dir)
            results = syncer.sync_all(
                wanted, list(segments) or None, max_pages=max_pages, full=full,
                all_companies=all_companies, max_items=max_items, years=list(years) or None,
            )
    except ValueError as exc:
        _finecim_fail(str(exc))
    except (FinecimAuthError, FinecimHTTPError) as exc:
        _finecim_fail(f"FINeCIM sync aborted: {exc}")
    finally:
        db.close()

    budget = max_pages or ("no limit" if full else DEFAULT_MAX_PAGES)
    table = Table(title=f"FINeCIM sync (page budget per entity and segment: {budget})")
    table.add_column("Entity", style="bold")
    for col in ("Pages", "Fetched", "Inserted", "Updated", "Skipped", "Errors"):
        table.add_column(col, justify="right")
    for entity, stats in results.items():
        err_style = "red" if stats.errors else "green"
        table.add_row(entity, str(stats.pages), str(stats.fetched), str(stats.inserted),
                      str(stats.updated), str(stats.skipped), f"[{err_style}]{stats.errors}[/{err_style}]")
    console.print(table)


class _ReadOnlySyncState:
    """Read-only view of finecim_sync for the dry run: opens the database file with
    ``mode=ro`` (no schema setup, no journal-mode change, no directory creation)."""

    def __init__(self, db_path: str) -> None:
        import sqlite3

        self.conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
        self.conn.row_factory = sqlite3.Row

    def get_finecim_sync(self, entity: str, segment_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT * FROM finecim_sync WHERE entity = ? AND segment_id = ?", (entity, segment_id),
        ).fetchone()
        return dict(row) if row else None

    def close(self) -> None:
        self.conn.close()


def _finecim_dry_run(config_dir: str, wanted: list[str], segments: list[str], max_pages, max_items,
                     full: bool, all_companies: bool, *, years: list[int] | None = None) -> None:
    """Print the plan of a sync: no credentials, no login, no network, no database writes.
    Unknown segments exit with code 1; the stored backfill cursors and head guards are
    shown when the database already exists."""
    from src.finecim.sync import PROFILE_REFRESH_DAYS, FinecimSync, item_budget

    db_path = _db_path(config_dir)
    db = None
    if os.path.isfile(db_path):
        try:
            db = _ReadOnlySyncState(db_path)
        except Exception:  # unreadable file: plan without the stored cursors
            db = None
    try:
        try:
            rows = FinecimSync(None, db, config_dir).plan(
                wanted, segments or None, max_pages=max_pages, full=full, max_items=max_items,
            )
        except ValueError as exc:
            _finecim_fail(str(exc))
    finally:
        if db is not None:
            db.close()

    console.print("FINeCIM sync (dry run): nothing is requested or written.", markup=False)
    steps = ["taxonomy", *(e for e in wanted if e != "taxonomy")]
    console.print(f"  steps:       {', '.join(steps)} (taxonomy always first)", markup=False)
    seg_list = list(dict.fromkeys(r["segment"] for r in rows))
    console.print(f"  segments:    {', '.join(seg_list)}", markup=False)
    items = item_budget(max_items, full)
    console.print(
        f"  max items: {items if items is not None else 'no limit'} per list entity and segment; "
        f"full: {full}; all companies: {all_companies}",
        markup=False,
    )
    if years and "summary" in wanted:
        console.print(f"  summaries:   refetch the stored months of {', '.join(map(str, years))}",
                      markup=False)
    if db is None:
        console.print(f"  database:    {db_path} does not exist yet (first run)", markup=False)

    table = Table(title="FINeCIM sync plan")
    for col in ("Entity", "Segment", "Page budget", "Position"):
        table.add_column(col)
    for r in rows:
        if r["skip"]:
            budget, position = "—", f"skipped ({r['skip']})"
        elif r["budget"] is None and r["entity"] in ("taxonomy", "company", "summary"):
            budget = {"taxonomy": "/subjekty page",
                      "company": "every profile" if full else f"profiles older than {PROFILE_REFRESH_DAYS} days",
                      "summary": "month list + new/recent months"}[r["entity"]]
            position = "—"
        else:
            budget = "no limit" if r["budget"] is None else str(r["budget"])
            position = _backfill_label(r["cursor"], r["complete"], guard=r.get("guard"))
        table.add_row(r["entity"], r["segment"], budget, position)
    console.print(table)


def _backfill_label(cursor, complete, *, short: bool = False, guard: int | None = None) -> str:
    # ``guard``: an unfinished head scan; the next run's head scan does not stop early
    # before it has passed this item id (finecim_sync.newest_id of a list entity)
    suffix = f", head unfinished (guard id {guard})" if guard is not None else ""
    if complete:
        return "complete" + suffix
    if cursor is not None:
        return (f"next page {cursor}" if short else f"backfill from page {cursor}") + suffix
    return ("not started" if short else "new (no backfill yet)") + suffix


@finecim.command("status")
@click.pass_context
def finecim_status(ctx):
    """Show the finecim_sync state (with backfill cursors) and row counts of the FINeCIM tables."""
    from src.finecim.sync import PROFILE_SYNC_ENTITY, resume_state

    config_dir = ctx.obj["config_dir"]
    db = _get_db(config_dir)
    try:
        db.initialize()
        rows = db.conn.execute("SELECT * FROM finecim_sync ORDER BY entity, segment_id").fetchall()
        segment_rows = [r for r in rows if r["entity"] != PROFILE_SYNC_ENTITY]
        profile_rows = [r for r in rows if r["entity"] == PROFILE_SYNC_ENTITY]
        if segment_rows:
            sync_table = Table(title="FINeCIM sync state")
            for col in ("Entity", "Segment", "Last run", "Last success", "Backfill", "Newest id / guard"):
                sync_table.add_column(col, no_wrap=col == "Backfill")
            sync_table.add_column("Note", overflow="fold")
            for r in segment_rows:
                if r["entity"] in ("news", "campaign", "mystery", "product"):
                    resume = resume_state(dict(r))
                    backfill = _backfill_label(resume.cursor, resume.complete, short=True,
                                               guard=resume.guard)
                else:
                    backfill = "—"
                sync_table.add_row(
                    r["entity"], r["segment_id"],
                    (r["last_run_at"] or "—").replace("T", " "),
                    (r["last_success_at"] or "—").replace("T", " "),
                    backfill,
                    "—" if r["newest_id"] is None else str(r["newest_id"]),
                    r["note"] or "",
                )
            console.print(sync_table)
        else:
            console.print("[yellow]No FINeCIM sync has run yet.[/yellow]")
        if profile_rows:
            fetched = [r["last_success_at"] for r in profile_rows if r["last_success_at"]]
            console.print(
                f"Company profiles fetched: {len(fetched)} of {len(profile_rows)} attempted"
                + (f"; oldest fetch {min(fetched).replace('T', ' ')}, newest {max(fetched).replace('T', ' ')}"
                   if fetched else ""),
                markup=False,
            )

        count_table = Table(title="FINeCIM data")
        count_table.add_column("Table", style="cyan")
        count_table.add_column("Rows", justify="right")
        count_table.add_column("From FINeCIM", justify="right")
        for name, label in _FINECIM_TABLES:
            total = db.conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            if name in _FINECIM_ID_TABLES:
                fc = db.conn.execute(f"SELECT COUNT(*) FROM {name} WHERE id LIKE 'fc-%'").fetchone()[0]
            else:
                fc = total
            count_table.add_row(f"{label} ({name})", str(total), str(fc))
        console.print(count_table)
    finally:
        db.close()


if __name__ == "__main__":
    cli()
