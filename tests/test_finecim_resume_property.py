"""Resume property of the FINeCIM sync: whatever the budgets, nothing listed is lost.

A deterministic simulator serves one FINeCIM news list (ids descending, newest first, 3
cards per page; new ids only ever enter at the top) to FinecimSync through a fake client.
List pages are rendered from the card markup of tests/fixtures/finecim/list_news.html and
detail pages from detail_news.html (the parser takes the id from the requested URL). The
detail parse is memoized per test (the page is the same for every id) to keep the
randomized runs fast; everything else is the production code path.
"""

import copy
import random
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from click.testing import CliRunner
from src import cli as cli_mod
from src.finecim import parsers
from src.finecim import sync as sync_mod
from src.finecim.sync import (
    DEFAULT_MAX_ITEMS,
    DEFAULT_MAX_PAGES,
    MAX_FREE_PAGES,
    MAX_PAGE_ATTEMPTS,
    PROFILE_REFRESH_DAYS,
    FinecimSync,
    resume_state,
)
from src.models.database import Database

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
FIXTURES = ROOT / "tests" / "fixtures" / "finecim"
PAGE_SIZE = 3
UNLIMITED = 10**6

_LIST = (FIXTURES / "list_news.html").read_text(encoding="utf-8")
_DETAIL = (FIXTURES / "detail_news.html").read_text(encoding="utf-8")


def _card_template() -> str:
    """The first article card of list_news.html, without the long annotation and tags."""
    start = _LIST.index('<div class="col-xxl-4')
    end = _LIST.index('<div class="col-xxl-4', start + 1)
    card = _LIST[start:end]
    card = re.sub(r'<div class="ecim-widget-article__body">.*?</div>\s*', "", card, count=1, flags=re.S)
    card = re.sub(r'<div class="kt-portlet__foot">.*?</div><!-- /foot -->', "", card, count=1, flags=re.S)
    assert "/cz/domena/ucty/news/43573" in card and ">new</li>" in card
    return card


_CARD = _card_template()


def render_list(ids: list[int], badged: set[int] = frozenset()) -> str:
    cards = []
    for item_id in ids:
        card = _CARD.replace("/news/43573", f"/news/{item_id}")
        if item_id in badged:
            card = card.replace(">new</li>", ">updated</li>")
        cards.append(card)
    return ('<html><body><div id="kt_content"><div class="row" id="snippet--listingItems">'
            + "".join(cards) + "</div></div></body></html>")


class SimList:
    """The list of one segment: ids newest first, new ids only at the top."""

    def __init__(self, archive: int = 0, start: int = 1000):
        self.next_id = start
        self.ids: list[int] = []
        self.ever: set[int] = set()
        self.insert(archive)

    def insert(self, n: int) -> None:
        new = list(range(self.next_id + n - 1, self.next_id - 1, -1))
        self.next_id += n
        self.ids[:0] = new
        self.ever.update(new)

    def delete_at(self, index: int) -> int:
        return self.ids.pop(index)

    def page(self, n: int) -> list[int]:
        return self.ids[(n - 1) * PAGE_SIZE:n * PAGE_SIZE]


class SimClient:
    """Serves SimList pages and detail pages; records list requests and detail fetches."""

    def __init__(self, sim: SimList):
        self.sim = sim
        self.badged: set[int] = set()
        self.failing: set[int] = set()
        self.list_requests = 0
        self.fetches: dict[int, int] = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def get(self, url: str, *, params: dict | None = None) -> str:
        parts = urlsplit(url)
        match = re.search(r"/news/(\d+)$", parts.path)
        if match:
            item_id = int(match.group(1))
            self.fetches[item_id] = self.fetches.get(item_id, 0) + 1
            if item_id in self.failing:
                return "<html><body><p>Něco se pokazilo</p></body></html>"  # parsers raise
            return _DETAIL
        assert parts.path.endswith("/ucty/news"), url
        page = int((params or {}).get("page") or parse_qs(parts.query).get("page", ["1"])[0])
        self.list_requests += 1
        return render_list(self.sim.page(page), self.badged)

    def get_fragment(self, url: str) -> str:
        return self.get(url)


@pytest.fixture
def fast_detail(monkeypatch):
    """parse_news_detail parsed once, then re-labelled per URL (the fixture is id-agnostic)."""
    real = parsers.parse_news_detail
    cache: dict[str, dict] = {}

    def parse(html: str, url: str) -> dict:
        if html is not _DETAIL:
            return real(html, url)
        if "d" not in cache:
            cache["d"] = real(html, url)
        d = copy.deepcopy(cache["d"])
        d.update(parsers._item_base(url))
        return d

    monkeypatch.setattr(parsers, "parse_news_detail", parse)


@pytest.fixture
def make_db(tmp_path):
    opened: list[Database] = []

    def make(name: str = "sim") -> Database:
        db = Database(str(tmp_path / f"{name}.sqlite"))
        db.conn.execute("PRAGMA synchronous=OFF")
        db.initialize()
        db.seed_segments(str(CONFIG_DIR))
        db.seed_competitors(str(CONFIG_DIR))
        opened.append(db)
        return db

    yield make
    for db in opened:
        db.close()


def stored_ids(db: Database) -> set[int]:
    rows = db.conn.execute("SELECT id FROM clanky WHERE id LIKE 'fc-news-%'").fetchall()
    return {int(r["id"][len("fc-news-"):]) for r in rows}


_SYNCERS: dict[tuple[int, int], FinecimSync] = {}


def run(db: Database, client: SimClient, **kw):
    """One sync_news run on segment ucty; returns (stats, list requests of this run)."""
    key = (id(db), id(client))
    if key not in _SYNCERS:  # reading the YAML config dominates otherwise
        _SYNCERS.clear()
        _SYNCERS[key] = FinecimSync(client, db, CONFIG_DIR)
    before = client.list_requests
    stats = _SYNCERS[key].sync_news(["ucty"], **kw)
    return stats, client.list_requests - before


def state(db: Database):
    return resume_state(db.get_finecim_sync("news", "ucty"))


def run_until_stable(db: Database, client: SimClient, limit: int = 40, **kw) -> int:
    """Plain runs until one fetches nothing and the list is complete; returns the run count."""
    for n in range(1, limit + 1):
        stats, _ = run(db, client, **kw)
        st = state(db)
        if stats.fetched == 0 and st.complete and st.guard is None:
            return n
    raise AssertionError(f"not stable after {limit} runs: {state(db)}")


# ── (1) the reviewer's seed-1015 sequence ───────────────────────


def test_reviewer_seed_1015_sequence_loses_nothing(make_db, fast_detail):
    db = make_db()
    sim = SimList(archive=6)
    client = SimClient(sim)
    run(db, client)
    for inserted, kw in ((12, {}), (8, {"max_pages": 3}), (12, {}), (0, {}), (0, {}), (12, {}),
                         (15, {"max_pages": 2})):
        sim.insert(inserted)
        run(db, client, **kw)
    run_until_stable(db, client)
    assert sim.ever <= stored_ids(db)
    assert set(client.fetches.values()) == {1}


def test_budget_cut_on_the_page_before_an_older_cut(make_db, fast_detail):
    """Two bursts that both overflow the budget, the second cut landing next to the first:
    the older pending tail is still fetched (the smaller guard is kept)."""
    db = make_db()
    sim = SimList(archive=30)
    client = SimClient(sim)
    run(db, client, full=True)
    assert state(db).complete
    sim.insert(12)  # 4 pages > budget 3
    run(db, client)
    st = state(db)
    assert st.complete and st.guard is not None
    first_guard = st.guard
    sim.insert(9)  # exactly the 3-page budget: the cut lands on the page before the old cut
    run(db, client)
    assert state(db).guard == first_guard  # the older (smaller) guard is kept
    run_until_stable(db, client)
    assert sim.ever <= stored_ids(db)
    assert set(client.fetches.values()) == {1}


# ── (2) randomized replay ────────────────────────────────────────


@pytest.mark.parametrize("seed", range(40))
def test_randomized_runs_lose_nothing(make_db, fast_detail, seed):
    rng = random.Random(seed)
    db = make_db(f"seed{seed}")
    sim = SimList(archive=rng.randint(0, 30))
    client = SimClient(sim)
    ever_badged: set[int] = set()
    for _ in range(25):
        sim.insert(rng.randint(0, 40))
        if len(sim.ids) > 2 and rng.random() < 0.25:
            sim.delete_at(rng.randint(1, len(sim.ids) - 1))  # exercises the vanished guard
        client.badged = set()
        stored = sorted(stored_ids(db) & set(sim.ids))
        if stored and rng.random() < 0.1:
            badge = rng.choice(stored)
            client.badged = {badge}
            ever_badged.add(badge)
        max_pages, max_items = rng.randint(1, 4), rng.randint(3, 30)
        stats, requests = run(db, client, max_pages=max_pages, max_items=max_items)
        assert requests <= max_pages + MAX_FREE_PAGES
        assert stats.fetched <= max_items
    client.badged = set()
    for _ in range(6):  # quiet runs, unlimited budgets
        run(db, client, max_pages=UNLIMITED, max_items=UNLIMITED)
    assert set(sim.ids) <= stored_ids(db)
    st = state(db)
    assert st.complete and st.guard is None
    for item_id, count in client.fetches.items():
        assert count == 1 or item_id in ever_badged, (item_id, count)
    # and a further plain run has nothing left to do
    stats, requests = run(db, client)
    assert (stats.fetched, requests) == (0, 1)


# ── (3) budget accounting ────────────────────────────────────────


def test_fully_known_pages_do_not_count_against_the_page_budget(make_db, fast_detail):
    db = make_db()
    sim = SimList(archive=30)  # 10 pages
    client = SimClient(sim)
    run(db, client, full=True)
    sim.insert(15)  # 5 pages of new items > budget 3
    run(db, client)
    guard = state(db).guard
    assert guard is not None
    # 3 more new pages on top; the run reads them (3 budget pages), then passes the 3 known
    # pages of the first burst for free and continues the first burst's tail (2 pages),
    # but the budget is spent after the 3 new pages
    sim.insert(9)
    stats, requests = run(db, client)
    assert stats.fetched == 9 and requests == 3
    # the next run reads 6 known pages for free, then the 2-page tail, then early-stops
    stats, requests = run(db, client)
    assert stats.fetched == 6
    assert requests == 6 + 2 + 1
    assert sim.ever <= stored_ids(db)
    st = state(db)
    assert st.complete and st.guard is None


def test_item_budget_cut_records_the_first_card_not_fetched(make_db, fast_detail):
    db = make_db()
    sim = SimList(archive=9)
    client = SimClient(sim)
    run(db, client, full=True)
    sim.insert(5)
    stats, _ = run(db, client, max_items=4)
    assert stats.fetched == 4
    st = state(db)
    assert st.complete
    assert st.guard == sim.ids[4]  # the 5th new item, first one not fetched
    stats, requests = run(db, client)
    assert stats.fetched == 1 and requests == 3  # pages 1 (known, free), 2 (the item), 3 (stop)
    assert state(db).guard is None


def test_default_item_budget(make_db, fast_detail):
    assert DEFAULT_MAX_ITEMS == 120
    db = make_db()
    sim = SimList(archive=200)
    client = SimClient(sim)
    stats, _ = run(db, client, max_pages=UNLIMITED)
    assert stats.fetched == DEFAULT_MAX_ITEMS
    st = state(db)
    assert st.cursor == DEFAULT_MAX_ITEMS // PAGE_SIZE + 1 and st.guard is None
    stats, _ = run(db, client, full=True)  # --full: no item budget
    assert stats.fetched == 200 - DEFAULT_MAX_ITEMS
    assert state(db).complete


def test_free_pages_are_capped(make_db, fast_detail):
    db = make_db()
    sim = SimList(archive=0)
    client = SimClient(sim)
    sim.insert(PAGE_SIZE * (MAX_FREE_PAGES + 10))
    run(db, client, full=True)
    # a guard far below the top (an unfinished head scan): every page above it is known
    db.set_finecim_sync("news", "ucty", newest_id=sim.ids[-1])
    stats, requests = run(db, client)
    assert stats.fetched == 0
    assert requests == MAX_FREE_PAGES
    st = state(db)
    # the cursor takes over below the pages that were read, the guard is dropped
    assert st.guard is None and st.cursor == MAX_FREE_PAGES + 1
    run_until_stable(db, client)


# ── (4) backfill retry ───────────────────────────────────────────


def test_backfill_page_with_failed_detail_is_read_again(make_db, fast_detail):
    db = make_db()
    sim = SimList(archive=9)  # pages: [1008..1006] [1005..1003] [1002..1000]
    client = SimClient(sim)
    run(db, client, max_pages=1)
    assert state(db).cursor == 2
    client.failing = {1004}
    for attempt in (1, 2):
        stats, _ = run(db, client, max_pages=1)
        assert stats.errors == 1
        st = state(db)
        assert st.cursor == 2 and st.retry == attempt  # the cursor stays on the page
        assert f"retry={attempt}" in db.get_finecim_sync("news", "ucty")["note"]
    client.failing = set()
    stats, _ = run(db, client, max_pages=1)
    assert stats.errors == 0
    assert {1005, 1004, 1003} <= stored_ids(db)
    st = state(db)
    assert st.cursor == 3 and st.retry == 0
    assert client.fetches[1004] == 3


def test_backfill_gives_up_on_a_page_after_three_attempts(make_db, fast_detail, caplog):
    assert MAX_PAGE_ATTEMPTS == 3
    db = make_db()
    sim = SimList(archive=9)
    client = SimClient(sim)
    run(db, client, max_pages=1)
    client.failing = {1004}
    for _ in range(MAX_PAGE_ATTEMPTS - 1):
        run(db, client, max_pages=1)
    with caplog.at_level("WARNING", logger="src.finecim.sync"):
        run(db, client, max_pages=1)
    assert state(db).cursor == 3
    assert any("list page 2" in r.getMessage() and "moves on" in r.getMessage() for r in caplog.records)


def test_removed_items_moving_cards_up_past_the_cursor_are_caught(make_db, fast_detail):
    db = make_db()
    sim = SimList(archive=18)  # 6 pages
    client = SimClient(sim)
    run(db, client)  # pages 1..3, cursor 4
    st = state(db)
    assert st.cursor == 4 and st.after == sim.page(3)[-1]
    first_unread = sim.ids[9]
    sim.delete_at(0)  # every card moves up one place: page 4's first card is now on page 3
    sim.delete_at(0)
    run(db, client)
    assert first_unread in stored_ids(db)
    run_until_stable(db, client)
    assert set(sim.ids) <= stored_ids(db)

# ── (4b) head-scan failures are resumable ────────────────────────


@pytest.mark.parametrize(("archive", "failing"), [(6, 1001), (12, 1007), (12, 1000)])
def test_head_scan_failed_detail_is_fetched_by_a_later_plain_run(make_db, fast_detail,
                                                                 archive, failing):
    db = make_db()
    sim = SimList(archive=archive)
    client = SimClient(sim)
    client.failing = {failing}
    stats, _ = run(db, client, max_pages=10, max_items=100)
    assert stats.errors == 1
    st = state(db)
    assert st.complete and st.guard == failing and st.head_retry == 1
    assert "hretry=1" in db.get_finecim_sync("news", "ucty")["note"]
    client.failing = set()
    stats, _ = run(db, client)
    assert stats.fetched == 1 and stats.errors == 0
    assert set(sim.ids) <= stored_ids(db)
    st = state(db)
    assert st.complete and st.guard is None and st.head_retry == 0
    assert client.fetches[failing] == 2
    stats, requests = run(db, client)
    assert (stats.fetched, requests) == (0, 1)


def test_full_run_with_a_failed_detail_is_completed_by_plain_runs(make_db, fast_detail):
    db = make_db()
    sim = SimList(archive=15)
    client = SimClient(sim)
    client.failing = {1003}
    run(db, client, full=True)
    client.failing = set()
    sim.insert(4)  # new items on top do not hide the failed card
    run_until_stable(db, client)
    assert set(sim.ids) <= stored_ids(db)


def test_head_scan_gives_up_on_a_detail_after_three_failed_runs(make_db, fast_detail, caplog):
    db = make_db()
    sim = SimList(archive=6)
    client = SimClient(sim)
    client.failing = {1004}
    for attempt in range(1, MAX_PAGE_ATTEMPTS):
        run(db, client)
        assert state(db).guard == 1004 and state(db).head_retry == attempt
    with caplog.at_level("WARNING", logger="src.finecim.sync"):
        run(db, client)
    st = state(db)
    assert st.guard is None and st.head_retry == 0 and st.complete
    assert any("1004" in r.getMessage() and "no longer" in r.getMessage() for r in caplog.records)
    assert client.fetches[1004] == MAX_PAGE_ATTEMPTS


@pytest.mark.parametrize("seed", range(30))
def test_randomized_runs_with_transient_detail_failures_lose_nothing(make_db, fast_detail, seed):
    rng = random.Random(10_000 + seed)
    db = make_db(f"fail{seed}")
    sim = SimList(archive=rng.randint(0, 30))
    client = SimClient(sim)
    for _ in range(25):
        sim.insert(rng.randint(0, 40))
        if len(sim.ids) > 2 and rng.random() < 0.25:
            sim.delete_at(rng.randint(1, len(sim.ids) - 1))
        # about 10% of the listed items fail in this run (transient: re-drawn every run)
        client.failing = {i for i in sim.ids if rng.random() < 0.1}
        max_pages, max_items = rng.randint(1, 4), rng.randint(3, 30)
        _, requests = run(db, client, max_pages=max_pages, max_items=max_items)
        assert requests <= max_pages + MAX_FREE_PAGES
    client.failing = set()
    for _ in range(6):
        run(db, client, max_pages=UNLIMITED, max_items=UNLIMITED)
    assert set(sim.ids) <= stored_ids(db)
    st = state(db)
    assert st.complete and st.guard is None


# ── (5) mystery pdf fallback, --years, dry-run label ─────────────


def test_mystery_pdf_url_falls_back_to_the_first_pdf_attachment(make_db, monkeypatch):
    from tests.test_finecim_sync import FakeClient

    db = make_db()
    real = parsers.parse_mystery_detail

    def without_body_pdf(html, url):
        d = real(html, url)
        d["pdf_url"] = None
        d["attachments"] = [{"name": "Prezentace", "url": "https://www.finecim.cz/media/pdf/open?itemId=777"}]
        return d

    monkeypatch.setattr(parsers, "parse_mystery_detail", without_body_pdf)
    FinecimSync(FakeClient(), db, CONFIG_DIR).sync_mystery(["ucty"], max_pages=1, max_items=1)
    row = db.conn.execute("SELECT pdf_url FROM mystery_shopping WHERE id = 'fc-ms-496'").fetchone()
    assert row["pdf_url"] == "https://www.finecim.cz/media/pdf/open?itemId=777"


def test_cli_years_reaches_sync_summaries(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cli_mod, "_setup_logging", lambda level="INFO": None)
    monkeypatch.setenv("FINECIM_USERNAME", "tester")
    monkeypatch.setenv("FINECIM_PASSWORD", "x")
    monkeypatch.setattr(cli_mod, "_make_finecim_client", lambda config_dir, creds: SimClient(SimList()))
    monkeypatch.setattr(FinecimSync, "sync_all", lambda self, *a, **kw: calls.append(kw) or {})
    config_dir = _cli_config(tmp_path)
    result = CliRunner().invoke(cli_mod.cli, ["--config-dir", str(config_dir), "finecim", "sync",
                                              "-e", "summary", "--years", "2025", "--years", "2026"])
    assert result.exit_code == 0, result.output
    assert calls and calls[0]["years"] == [2025, 2026]


def test_sync_all_passes_years_to_summaries(make_db, monkeypatch):
    seen = []
    monkeypatch.setattr(FinecimSync, "sync_taxonomy", lambda self, segments=None: sync_mod.SyncStats())
    monkeypatch.setattr(FinecimSync, "sync_summaries",
                        lambda self, segments=None, **kw: seen.append(kw) or sync_mod.SyncStats())
    FinecimSync(SimClient(SimList()), make_db(), CONFIG_DIR).sync_all(["summary"], ["ucty"], years=[2024])
    assert seen == [{"years": [2024], "max_items": None}]


def test_dry_run_labels(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_mod, "_setup_logging", lambda level="INFO": None)
    monkeypatch.setattr(cli_mod, "_make_finecim_client", lambda *a: pytest.fail("no client in a dry run"))
    config_dir = _cli_config(tmp_path)
    db = Database(str(tmp_path / "cli.sqlite"))
    db.initialize()
    db.set_finecim_sync("news", "ucty", newest_id=4242, note="complete; fetched=0")
    db.set_finecim_sync("campaign", "ucty", last_page=5, note="backfill; after=77; fetched=0")
    db.close()
    result = CliRunner().invoke(cli_mod.cli, ["--config-dir", str(config_dir), "finecim", "sync", "--dry-run",
                                              "-s", "ucty", "--years", "2026"])
    assert result.exit_code == 0, result.output
    out = " ".join(re.sub(r"\x1b\[[0-9;]*m", "", result.output).split())
    assert f"profiles older than {PROFILE_REFRESH_DAYS} days" in out
    assert f"max items: {DEFAULT_MAX_ITEMS} per list entity and segment" in out
    assert "refetch the stored months of 2026" in out
    assert "guard id 4242" in out
    assert "backfill from page 5" in out
    assert str(DEFAULT_MAX_PAGES) in out


def _cli_config(tmp_path) -> Path:
    import yaml

    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    (config_dir / "settings.yaml").write_text(
        yaml.safe_dump({"database": {"path": str(tmp_path / "cli.sqlite")}, "finecim": {"schedule": "daily"}}),
        encoding="utf-8",
    )
    for name in ("segments.yaml", "finecim.yaml", "competitors.yaml"):
        src = CONFIG_DIR / name
        if src.exists():
            (config_dir / name).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    return config_dir
