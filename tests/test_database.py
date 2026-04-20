from src.models import Signal


def test_seed_competitors(seeded_db):
    competitors = seeded_db.get_competitors()
    assert len(competitors) == 1
    assert competitors[0]["id"] == "acme_bank"
    assert competitors[0]["ico"] == "12345678"


def test_insert_signal_is_idempotent_on_content_hash(seeded_db):
    sig = Signal(
        competitor_id="acme_bank", source="ares", signal_type="board_change",
        title="New board member", content="Jane Doe",
    )
    assert seeded_db.insert_signal(sig.to_dict()) is True
    # Re-inserting the same content must be a no-op (UNIQUE content_hash).
    dup = Signal(
        competitor_id="acme_bank", source="ares", signal_type="board_change",
        title="New board member", content="Jane Doe",
    )
    assert seeded_db.insert_signal(dup.to_dict()) is False


def test_signal_filtering(seeded_db):
    for sev, title in [(1, "low"), (3, "mid"), (5, "high")]:
        seeded_db.insert_signal(
            Signal(
                competitor_id="acme_bank", source="news", signal_type="news_article",
                title=title, content=title, severity=sev,
            ).to_dict()
        )
    high_only = seeded_db.get_signals(min_severity=4)
    assert len(high_only) == 1
    assert high_only[0]["title"] == "high"


def test_snapshot_insert_and_latest(seeded_db):
    seeded_db.insert_snapshot("acme_bank", "ares", "ares_api:12345678", "{}", "hash1")
    seeded_db.insert_snapshot("acme_bank", "ares", "ares_api:12345678", '{"x":1}', "hash2")
    latest = seeded_db.get_latest_snapshot("acme_bank", "ares", "ares_api:12345678")
    assert latest["content_hash"] == "hash2"
    prev = seeded_db.get_previous_snapshot("acme_bank", "ares", "ares_api:12345678")
    assert prev["content_hash"] == "hash1"


def test_collector_run_lifecycle(seeded_db):
    run_id = seeded_db.start_collector_run("ares", "acme_bank")
    seeded_db.finish_collector_run(run_id, "success", signals_found=3)
    runs = seeded_db.get_collector_status()
    assert runs[0]["status"] == "success"
    assert runs[0]["signals_found"] == 3


def test_overview_aggregates(seeded_db):
    for sev in (2, 3, 4):
        seeded_db.insert_signal(
            Signal(
                competitor_id="acme_bank", source="news", signal_type="news_article",
                title=f"t{sev}", severity=sev,
            ).to_dict()
        )
    overview = seeded_db.get_signals_overview()
    assert overview["total_signals"]["total_signals"] == 3
    sources = {row["source"]: row["count"] for row in overview["by_source"]}
    assert sources.get("news") == 3
