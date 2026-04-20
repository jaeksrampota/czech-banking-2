import json
from pathlib import Path

import pytest
import yaml
from src.models.database import Database


@pytest.fixture
def tmp_db(tmp_path) -> Database:
    db = Database(str(tmp_path / "test.sqlite"))
    db.initialize()
    yield db
    db.close()


@pytest.fixture
def tmp_config_dir(tmp_path) -> Path:
    config_dir = tmp_path / "config"
    (config_dir / "competitors").mkdir(parents=True)
    (config_dir / "settings.yaml").write_text(
        yaml.safe_dump(
            {
                "database": {"path": "data/db/test.sqlite"},
                "collectors": {
                    "ares": {"schedule": "weekly"},
                    "job_postings": {"schedule": "daily"},
                    "news": {"schedule": "hourly"},
                },
            }
        ),
        encoding="utf-8",
    )
    (config_dir / "sources.yaml").write_text(
        yaml.safe_dump({"industry_feeds": []}), encoding="utf-8"
    )
    return config_dir


@pytest.fixture
def seeded_db(tmp_db, tmp_config_dir) -> Database:
    comp_dir = tmp_config_dir / "competitors"
    (comp_dir / "acme_bank.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "acme_bank",
                "name": "ACME Bank",
                "parent_group": "ACME Group",
                "tier": 2,
                "sources": {
                    "ares_ico": "12345678",
                    "careers_search_name": "ACME Bank",
                    "news_rss": "https://example.invalid/rss",
                },
                "aliases": ["ACME", "AcmeBank"],
            }
        ),
        encoding="utf-8",
    )
    tmp_db.seed_competitors(str(tmp_config_dir))
    return tmp_db
