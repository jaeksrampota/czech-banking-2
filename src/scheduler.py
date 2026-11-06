"""APScheduler-based runner that honors settings.yaml schedules.

Wires each collector (ares/jobs/news) to a cron-ish trigger derived from
settings.collectors.<name>.schedule. Supported values:

    hourly  →  every hour at :05
    daily   →  04:15 UTC
    weekly  →  Monday 04:30 UTC

Anything else is treated as a plain cron expression (5 fields) and handed to
APScheduler directly. Use `python -m src.cli schedule` to run the daemon.

FINeCIM: when settings.finecim.schedule is set (default "daily") and the FINeCIM
credentials resolve, a `finecim_sync` job runs FinecimSync.sync_all() with the bounded
defaults (sync.DEFAULT_MAX_PAGES list pages with detail fetches and sync.DEFAULT_MAX_ITEMS
detail fetches per entity and segment: new items first, then the next slice of the
backfill); otherwise a log line says FINeCIM is disabled.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import yaml
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.collectors.ares import AresCollector
from src.collectors.job_postings import JobPostingsCollector
from src.collectors.news import NewsCollector
from src.collectors.website import WebsiteCollector
from src.models.database import Database

logger = logging.getLogger(__name__)

# Named schedules (and cron expressions) are in UTC, like the BlockingScheduler: a trigger
# keeps its own timezone, so without an explicit one it would use the machine's local zone.
_NAMED_SCHEDULES: dict[str, CronTrigger] = {
    "hourly": CronTrigger(minute=5, timezone="UTC"),
    "daily": CronTrigger(hour=4, minute=15, timezone="UTC"),
    "weekly": CronTrigger(day_of_week="mon", hour=4, minute=30, timezone="UTC"),
}

_COLLECTOR_FACTORIES: dict[str, Callable] = {
    "ares": AresCollector,
    "job_postings": JobPostingsCollector,
    "news": NewsCollector,
    "website": WebsiteCollector,
}


def parse_trigger(schedule: str) -> CronTrigger:
    """Return an APScheduler trigger for one of the named shortcuts or a cron expr."""
    named = _NAMED_SCHEDULES.get(schedule.strip().lower())
    if named is not None:
        return named
    return CronTrigger.from_crontab(schedule, timezone="UTC")


def build_scheduler(db_path: str, config_dir: str) -> BlockingScheduler:
    settings_path = Path(config_dir) / "settings.yaml"
    settings = (
        yaml.safe_load(settings_path.read_text(encoding="utf-8"))
        if settings_path.exists()
        else {}
    )
    collectors_cfg = settings.get("collectors", {})

    scheduler = BlockingScheduler(timezone="UTC")

    for name, factory in _COLLECTOR_FACTORIES.items():
        schedule = collectors_cfg.get(name, {}).get("schedule")
        if not schedule:
            logger.info("No schedule for %s — skipping", name)
            continue
        trigger = parse_trigger(schedule)
        scheduler.add_job(
            _make_runner(factory, db_path, config_dir),
            trigger=trigger,
            id=f"collect_{name}",
            name=f"collect_{name}",
            misfire_grace_time=60 * 30,
            coalesce=True,
            max_instances=1,
        )
        logger.info("Scheduled %s @ %s", name, schedule)

    _add_finecim_job(scheduler, settings, db_path, config_dir)
    return scheduler


def _make_runner(factory: Callable, db_path: str, config_dir: str):
    def _run():
        db = Database(db_path)
        try:
            db.initialize()
            collector = factory(db, config_dir)
            with collector:
                results = collector.run()
            logger.info(
                "[%s] scheduled run: %d new signals, %d errors",
                collector.name,
                results.get("new_signals", 0),
                results.get("errors", 0),
            )
        except Exception:
            logger.exception("Scheduled run failed for %s", factory.__name__)
        finally:
            db.close()

    return _run


def _add_finecim_job(scheduler: BlockingScheduler, settings: dict, db_path: str, config_dir: str) -> None:
    """Add the daily FINeCIM sync when credentials resolve; otherwise log that it is disabled."""
    from src.finecim.credentials import CredentialsError, load_credentials

    schedule = (settings.get("finecim") or {}).get("schedule", "daily")
    if not schedule or str(schedule).strip().lower() in ("off", "none", "disabled", "false"):
        logger.info("FINeCIM sync disabled in settings.yaml")
        return
    try:
        creds = load_credentials()
    except CredentialsError:
        logger.info("FINeCIM sync disabled: no credentials (see finecim-research/SCRAPER.md)")
        return
    scheduler.add_job(
        _make_finecim_runner(db_path, config_dir),
        trigger=parse_trigger(str(schedule)),
        id="finecim_sync",
        name="finecim_sync",
        misfire_grace_time=60 * 60,
        coalesce=True,
        max_instances=1,
    )
    logger.info("Scheduled finecim_sync @ %s (credentials from %s)", schedule, creds.source)


def _make_finecim_runner(db_path: str, config_dir: str):
    def _run():
        from src.finecim.credentials import load_credentials
        from src.finecim.sync import DEFAULT_MAX_ITEMS, DEFAULT_MAX_PAGES, FinecimSync, client_from_settings

        db = Database(db_path)
        try:
            db.initialize()
            with client_from_settings(config_dir, load_credentials()) as client:
                results = FinecimSync(client, db, config_dir).sync_all(
                    max_pages=DEFAULT_MAX_PAGES, max_items=DEFAULT_MAX_ITEMS,
                )
            for entity, stats in results.items():
                logger.info("[finecim] %s: %s", entity, stats.as_dict())
        except Exception:
            logger.exception("Scheduled FINeCIM sync failed")
        finally:
            db.close()

    return _run
