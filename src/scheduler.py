"""APScheduler-based runner that honors settings.yaml schedules.

Wires each collector (ares/jobs/news) to a cron-ish trigger derived from
settings.collectors.<name>.schedule. Supported values:

    hourly  →  every hour at :05
    daily   →  04:15 UTC
    weekly  →  Monday 04:30 UTC

Anything else is treated as a plain cron expression (5 fields) and handed to
APScheduler directly. Use `python -m src.cli schedule` to run the daemon.
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

_NAMED_SCHEDULES: dict[str, CronTrigger] = {
    "hourly": CronTrigger(minute=5),
    "daily": CronTrigger(hour=4, minute=15),
    "weekly": CronTrigger(day_of_week="mon", hour=4, minute=30),
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
    return CronTrigger.from_crontab(schedule)


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
