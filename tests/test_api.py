import pytest
from src.api import create_app
from src.models import Signal


@pytest.fixture
def client(tmp_path, seeded_db, monkeypatch):
    monkeypatch.delenv("CI_MONITOR_API_KEY", raising=False)
    seeded_db.insert_signal(
        Signal(
            competitor_id="acme_bank", source="news", signal_type="news_article",
            title="ČNB pokuta", content="regulace", severity=4,
            tags=["news"], metadata={"foo": "bar"},
        ).to_dict()
    )
    db_path = seeded_db.db_path
    seeded_db.close()  # api.py opens its own connection
    app = create_app(db_path)
    app.config["TESTING"] = True
    return app.test_client()


def test_signals_endpoint_returns_parsed_tags(client):
    resp = client.get("/api/signals")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload
    assert payload[0]["tags"] == ["news"]
    assert payload[0]["metadata"] == {"foo": "bar"}


def test_summary_endpoint_shape(client):
    resp = client.get("/api/summary")
    assert resp.status_code == 200
    data = resp.get_json()
    assert "total_signals" in data
    assert "severity_distribution" in data
    assert "recent_signals" in data


def test_competitors_endpoint_enriches_with_stats(client):
    resp = client.get("/api/competitors")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data[0]["id"] == "acme_bank"
    assert data[0]["signal_count"] >= 1


def test_api_auth_required_when_env_set(tmp_path, seeded_db, monkeypatch):
    monkeypatch.setenv("CI_MONITOR_API_KEY", "s3cret")
    db_path = seeded_db.db_path
    seeded_db.close()
    app = create_app(db_path)
    client = app.test_client()
    assert client.get("/api/signals").status_code == 401
    assert client.get("/api/signals", headers={"X-API-Key": "s3cret"}).status_code == 200
    assert client.get("/api/signals?api_key=s3cret").status_code == 200
