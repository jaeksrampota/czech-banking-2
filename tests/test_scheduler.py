from apscheduler.triggers.cron import CronTrigger
from src.scheduler import build_scheduler, parse_trigger


def test_parse_named_schedules():
    for name in ("hourly", "daily", "weekly"):
        assert isinstance(parse_trigger(name), CronTrigger)


def test_parse_cron_expression():
    trigger = parse_trigger("0 3 * * *")
    assert isinstance(trigger, CronTrigger)


def test_build_scheduler_adds_jobs(tmp_config_dir, tmp_path):
    db_path = str(tmp_path / "ci.sqlite")
    scheduler = build_scheduler(db_path, str(tmp_config_dir))
    job_ids = {j.id for j in scheduler.get_jobs()}
    assert {"collect_ares", "collect_job_postings", "collect_news"} <= job_ids
