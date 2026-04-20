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


def _get_db(config_dir: str) -> Database:
    settings_path = Path(config_dir) / "settings.yaml"
    if settings_path.exists():
        settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        db_path = settings.get("database", {}).get("path", "data/db/ci_monitor.sqlite")
    else:
        db_path = "data/db/ci_monitor.sqlite"

    # Make path relative to project root
    if not os.path.isabs(db_path):
        db_path = str(PROJECT_ROOT / db_path)

    return Database(db_path)


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
    """Initialize database and seed competitors from config."""
    config_dir = ctx.obj["config_dir"]
    db = _get_db(config_dir)
    db.initialize()
    db.seed_competitors(config_dir)

    competitors = db.get_competitors()
    table = Table(title="Competitors Loaded")
    table.add_column("ID", style="cyan")
    table.add_column("Name", style="bold")
    table.add_column("Tier")
    table.add_column("IČO")

    for c in competitors:
        table.add_row(c["id"], c["name"], str(c["tier"]), c.get("ico", "—"))

    console.print(table)
    console.print(f"[green]Database initialized with {len(competitors)} competitors.[/green]")
    db.close()


@cli.command()
@click.option("--source", "-s", type=click.Choice(["ares", "jobs", "news", "all"]), default="all")
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


if __name__ == "__main__":
    cli()
