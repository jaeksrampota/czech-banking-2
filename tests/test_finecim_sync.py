"""FinecimSync orchestration, the finecim CLI group and the scheduler hook (no network).

A FakeClient serves the trimmed live pages in tests/fixtures/finecim/ by URL pattern. Detail
fixtures exist once per entity; parsers take the id from the requested URL, so every card id
of a list fixture gets its own row.
"""

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
import yaml
from click.testing import CliRunner
from src import cli as cli_mod
from src.finecim import credentials as cred_mod
from src.finecim import sync as sync_mod
from src.finecim.client import FinecimAuthError
from src.finecim.sync import (
    DEFAULT_MAX_ITEMS,
    DEFAULT_MAX_PAGES,
    ENTITIES,
    PROFILE_SYNC_ENTITY,
    SYNC_TARGETS,
    FinecimSync,
    SyncStats,
    backfill_position,
    needs_fetch,
    resume_state,
)
from src.models.database import FINECIM_PLACEHOLDER_COMPETITOR, Database

ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = ROOT / "config"
FIXTURES = ROOT / "tests" / "fixtures" / "finecim"

NEWS_IDS = {43573, 43568, 43566}
NEWS_PAGE2_IDS = {43194, 43179}
CAMPAIGN_IDS = {4695, 4686, 4677}
MYSTERY_IDS = {496, 495, 494}
PRODUCT_IDS = {3936, 3934, 3939}


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


#: A list page with no cards (what an empty domain or a page past the end returns).
EMPTY_LISTING = (
    '<html><body><div id="kt_content"><div id="snippet--listingItems"></div>'
    '<div id="snippet--listing"></div><div id="snippet--content"><div class="row"></div></div>'
    '<p>Nebyly nalezeny žádné záznamy.</p></div></body></html>'
)


class FakeClient:
    """Serves fixture files by URL pattern and records every request.

    ``overrides`` maps a fixture file name to replacement HTML; ``broken`` is a set of URL
    substrings answered with a page that is not the expected type (parsers raise ParseError).
    ``pages`` maps ``(path suffix, page)`` of a list URL to replacement HTML (e.g.
    ``{("/ucty/news", 3): EMPTY_LISTING}``); ``empty`` is a set of path substrings whose list
    pages (not details) are answered with EMPTY_LISTING.
    """

    def __init__(self, overrides: dict[str, str] | None = None, broken: set[str] | None = None,
                 pages: dict[tuple[str, int], str] | None = None, empty: set[str] | None = None):
        self.overrides = overrides or {}
        self.broken = broken or set()
        self.pages = pages or {}
        self.empty = empty or set()
        self.requests: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def _file(self, name: str) -> str:
        return self.overrides.get(name) or _fixture(name)

    def get(self, path_or_url: str, *, params: dict | None = None) -> str:
        url = path_or_url
        if params:
            url += ("&" if "?" in url else "?") + "&".join(f"{k}={v}" for k, v in params.items())
        self.requests.append(url)
        if any(b in url for b in self.broken):
            return "<html><body><p>Něco se pokazilo</p></body></html>"
        parts = urlsplit(url)
        path, query = parts.path, parse_qs(parts.query)
        page = int(query.get("page", ["1"])[0])
        is_detail = re.search(r"/\d+$", path) is not None or "do" in query
        if not is_detail:
            for (suffix, wanted_page), html in self.pages.items():
                if path.endswith(suffix) and page == wanted_page:
                    return html
            if any(e in path for e in self.empty):
                return EMPTY_LISTING
        if query.get("do") == ["campaignCreatives"]:
            html = self._file("campaign_creatives.html")
            match = re.search(r"/campaign/(\d+)$", path)
            if match and match.group(1) != "4695":
                # Creative ids are global on the site; keep other campaigns' creatives distinct.
                html = html.replace("creativeId=", f"creativeId={match.group(1)}")
            return html
        match = re.search(r"/campaign/(\d+)$", path)
        if match and match.group(1) != "4695":
            # The detail fixture is campaign 4695; point its creatives buttons at the requested id.
            cid = match.group(1)
            return self._file("detail_campaign.html").replace("campaign/4695", f"campaign/{cid}").replace(
                "campaign%2F4695", f"campaign%2F{cid}"
            )
        if "/produkty/parameters-new-window/" in path:
            return self._file("product_parameters.html")
        if path.endswith("/subjekty"):
            return self._file("list_subjekty.html")
        match = re.search(r"/executive-summary/(\d+)$", path)
        if match:
            html = self._file("detail_executive_summary.html")
            if match.group(1) != "10664":
                # Entry ids are global on the site; keep other months' entries distinct.
                html = html.replace('es-entry-picker" value="', f'es-entry-picker" value="{match.group(1)}')
            return html
        if path.endswith("/executive-summary"):
            return self._file("list_executive_summary.html")
        routes = (
            (r"/news/\d+$", "detail_news.html"),
            (r"/campaign/\d+$", "detail_campaign.html"),
            (r"/mystery-shopping/\d+$", "detail_mystery.html"),
            (r"/produkt/\d+$", "detail_product.html"),
            (r"/subjekt/\d+$", "detail_company.html"),
        )
        for pattern, name in routes:
            if re.search(pattern, path):
                return self._file(name)
        lists = {
            "/news": "list_news_page2_step96.html" if page == 2 else "list_news.html",
            "/campaign": "list_campaign.html",
            "/mystery-shopping": "list_mystery.html",
            "/produkty": "list_products.html",
        }
        for suffix, name in lists.items():
            if path.endswith(suffix):
                return self._file(name)
        raise AssertionError(f"FakeClient has no fixture for {url}")

    def get_fragment(self, url: str) -> str:
        return self.get(url)

    # -- request accounting ----------------------------------------------------------

    def details(self) -> list[str]:
        """Requests other than list pages (details, creatives, parameters, profiles)."""
        return [
            u for u in self.requests
            if re.search(r"/(news|campaign|mystery-shopping|produkt|subjekt|executive-summary)/\d+", u)
            or "parameters-new-window" in u
        ]

    def count(self, pattern: str) -> int:
        return sum(1 for u in self.requests if re.search(pattern, u))


@pytest.fixture
def db(tmp_path) -> Database:
    database = Database(str(tmp_path / "finecim_sync.sqlite"))
    database.initialize()
    database.seed_segments(str(CONFIG_DIR))
    database.seed_competitors(str(CONFIG_DIR))
    yield database
    database.close()


def _syncer(db: Database, client: FakeClient) -> FinecimSync:
    return FinecimSync(client, db, CONFIG_DIR)


def _ids(db: Database, table: str, prefix: str) -> set[int]:
    rows = db.conn.execute(f"SELECT id FROM {table} WHERE id LIKE ?", (prefix + "%",)).fetchall()
    return {int(r["id"][len(prefix):]) for r in rows}


def _count(db: Database, table: str, where: str = "1=1", params: tuple = ()) -> int:
    return db.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]


# ── the incremental rule ─────────────────────────────────────────


def test_needs_fetch_rule():
    assert needs_fetch({"date": "2026-11-05"}, False, None, "date")
    assert not needs_fetch({"date": "2026-11-05"}, True, "2026-11-05", "date")
    assert needs_fetch({"date": "2026-11-06"}, True, "2026-11-05", "date")
    # A badge is not enough when the card date proves the stored copy is current...
    assert not needs_fetch({"updated_date": "2026-11-02", "badges": ["updated"]}, True, "2026-11-02",
                           "updated_date", True)
    # ...but a publish date (news, mystery) proves nothing: the badge forces a refetch.
    assert needs_fetch({"date": "2026-11-02", "badges": ["updated"]}, True, "2026-11-02", "date")
    # ...but it is when the card has no comparable date (products).
    assert needs_fetch({"badges": ["updated"]}, True, "2026-09-01", None)
    assert not needs_fetch({"badges": ["new"]}, True, "2026-09-01", None)


# ── sync_all ─────────────────────────────────────────────────────


def test_sync_all_inserts_expected_rows(db):
    # page 2 of every list is empty, so segments whose page 1 holds only cards already
    # fetched in this run (other domains) finish their backfill without new rows
    client = FakeClient(pages=_two_page_lists())
    results = _syncer(db, client).sync_all(max_pages=1)

    assert set(results) == set(SYNC_TARGETS)
    # the network taxonomy runs first: one /subjekty page per segment, reused by "company"
    assert client.requests[0].endswith("/subjekty")
    assert client.count(r"/subjekty$") == 10
    assert results["taxonomy"].pages == 10
    assert all(isinstance(s, SyncStats) for s in results.values())
    assert sum(s.errors for s in results.values()) == 0

    # news
    assert _ids(db, "clanky", "fc-news-") == NEWS_IDS
    news = db.conn.execute("SELECT * FROM clanky WHERE id = 'fc-news-43573'").fetchone()
    assert news["segment_id"] == "ucty"
    assert news["competitor_id"] == "mbank"  # related subject 52 -> mbank
    assert news["datum"] == "2026-11-05"
    assert news["typ_zpravy"] == "produkty a služby, tiskové zprávy"
    assert news["stav"] == "new"
    assert news["perex"].startswith("Klienti mBank")
    assert "<p>" in news["telo"]
    tags = json.loads(news["tagy"])
    assert len(tags) == 2 and tags[0] == "mobilní bankovnictví"
    assert news["url"] == "https://www.finecim.cz/cz/domena/ucty/news/43573"
    assert _count(db, "finecim_vazby", "entity_type = 'clanek' AND entity_id = 'fc-news-43573'") == 1
    assert results["news"].inserted == 3

    # campaigns with creatives
    assert _ids(db, "kampane", "fc-campaign-") == CAMPAIGN_IDS
    camp = db.conn.execute("SELECT * FROM kampane WHERE id = 'fc-campaign-4695'").fetchone()
    assert camp["competitor_id"] == "air_bank"
    assert camp["zacatek"] == "2026-11-01"
    assert camp["aktualizace"] == "2026-11-02"
    assert json.loads(camp["media_typy"]) == ["TV"]
    assert camp["typ_kampane"] == "Produktová, Imageová"
    assert camp["kreativa_url"].endswith("/media/image/default/62334")
    for cid in CAMPAIGN_IDS:
        assert _count(db, "kampane_kreativy", "kampan_id = ?", (f"fc-campaign-{cid}",)) >= 1
    creative = db.conn.execute(
        "SELECT * FROM kampane_kreativy WHERE kampan_id = 'fc-campaign-4695' ORDER BY datum DESC"
    ).fetchone()
    assert creative["media_typ"] == "TV"
    assert creative["media_druh"] == "video"
    assert creative["media_url"].startswith("https://www.finecim.cz/media/download/default/")
    assert creative["id"].startswith("fc-creative-")
    assert client.count(r"do=campaignCreatives") == 3

    # mystery shopping
    assert _ids(db, "mystery_shopping", "fc-ms-") == MYSTERY_IDS
    ms = db.conn.execute("SELECT * FROM mystery_shopping WHERE id = 'fc-ms-496'").fetchone()
    assert ms["competitor_id"] == "ceska_sporitelna"
    assert ms["datum"] == "2026-10-14"
    assert ms["pdf_url"] == "https://www.finecim.cz/media/pdf/open?itemId=22639"
    assert ms["popis"].startswith("Česká spořitelna")
    assert _count(db, "finecim_prilohy", "entity_type = 'mystery' AND entity_id = 'fc-ms-496'") == 1

    # products with parameters
    assert _ids(db, "produkty", "fc-product-") == PRODUCT_IDS
    prod = db.conn.execute("SELECT * FROM produkty WHERE id = 'fc-product-3936'").fetchone()
    assert prod["competitor_id"] == "unicredit"
    assert prod["produktova_linie_id"] == "ucty__mobilni_aplikace"
    assert prod["zakaznicky_segment"] == "Fyzické osoby"
    assert prod["aktivni"] == 1
    assert prod["aktualizace"] == "2026-09-01"
    params = json.loads(prod["atributy"])
    assert len(params) == 12
    assert params[0] == {"section": "Aktuální verze", "name": "iOS (verze)", "value": "26.4.51"}
    assert client.count(r"parameters-new-window") == 3

    # subjects from the list (+ membership), profiles only for mapped competitors
    subject_list_ids = {71, 351, 119, 105, 11, 43, 190, 115}
    stored = {r["subject_id"] for r in db.conn.execute("SELECT subject_id FROM finecim_subjekty")}
    assert subject_list_ids <= stored
    air = db.get_finecim_subject(71)
    assert air["competitor_id"] == "air_bank"
    assert air["logo_url"].startswith("https://www.finecim.cz/media/image/default/")
    assert "ucty" in air["segment_ids"]
    assert _count(db, "finecim_subjekty_segmenty", "segment_id = 'ucty'") == 27
    assert db.get_finecim_subject(351)["competitor_id"] is None  # Penta Bank: unmapped
    profile = db.conn.execute(
        "SELECT * FROM spolecnost_detail WHERE competitor_id = 'trinity_bank'"
    ).fetchone()
    assert profile["sidlo"].startswith("Celetná")
    assert profile["pocet_klientu"] == 200000
    assert json.loads(profile["socialni_site"])["web"] == "https://www.trinitybank.cz/"
    assert len(json.loads(profile["predstavenstvo"])) == 5
    assert _count(db, "finecim_prilohy", "entity_type = 'spolecnost' AND entity_id = 'trinity_bank'") == 3
    # one profile per mapped subject on the list, none for unmapped subjects
    assert client.count(r"/subjekt/\d+") == 19
    assert client.count(r"/subjekt/351$") == 0
    assert _count(db, "competitors", "id LIKE 'fc_%'") == 0

    # executive summary 10664 with 4 entries
    es = db.conn.execute("SELECT * FROM executive_summary WHERE id = 'fc-es-10664'").fetchone()
    assert (es["segment_id"], es["rok"], es["mesic"]) == ("ucty", 2026, 6)
    assert es["nazev"] == "červen 2026"
    assert es["telo"].count("\n") == 3
    assert es["telo"].startswith("- [Digital Share of Reach Tracker 05/26](https://www.finecim.cz/")
    entries = db.conn.execute(
        "SELECT * FROM executive_summary_polozky WHERE summary_id = 'fc-es-10664' ORDER BY poradi"
    ).fetchall()
    assert [e["id"] for e in entries] == [
        "fc-es-entry-45835", "fc-es-entry-45856", "fc-es-entry-45834", "fc-es-entry-45846",
    ]
    assert entries[0]["clanek_id"] == "fc-news-42857"
    assert _count(db, "executive_summary", "id LIKE 'fc-es-%'") == 11

    # finecim_sync bookkeeping
    state = db.get_finecim_sync("news", "ucty")
    assert state["last_success_at"] and state["last_run_at"]
    assert state["newest_id"] is None  # no head guard pending
    # budget of 1 page spent on page 1 with new items: the backfill continues at page 2
    assert state["last_page"] == 2
    assert state["note"].startswith("backfill")
    assert db.get_finecim_sync("product", "fintech") is None  # no products tab
    assert db.get_finecim_sync("summary", "ucty")["newest_id"] == 10677


def _two_page_lists() -> dict[tuple[str, int], str]:
    """List rules that end every list after page 1 (page 2 is empty)."""
    return {(suffix, 2): EMPTY_LISTING for suffix in ("/news", "/campaign", "/mystery-shopping", "/produkty")}


def test_second_run_fetches_no_details(db):
    # first run: page 1 has new items, page 2 is empty -> every list is complete
    _syncer(db, FakeClient(pages=_two_page_lists())).sync_all()
    assert _news_state(db) == (None, True)
    counts = {t: _count(db, t) for t in ("clanky", "kampane", "kampane_kreativy", "mystery_shopping",
                                          "produkty", "executive_summary", "finecim_subjekty")}

    client = FakeClient(pages=_two_page_lists())
    # page 1 has nothing new (early stop) and the lists are complete: nothing else to read
    results = _syncer(db, client).sync_all()

    assert client.details() == []
    assert sum(s.inserted for s in results.values()) == 0
    assert sum(s.fetched for s in results.values()) == 0
    assert sum(s.errors for s in results.values()) == 0
    # one list page per segment and entity
    assert client.count(r"/ucty/news\?") == 1
    assert counts == {t: _count(db, t) for t in counts}


def test_news_pagination_and_early_stop(db):
    client = FakeClient()
    stats = _syncer(db, client).sync_news(["ucty"])
    # page 1 (3 new) -> page 2 (2 new) -> page 3 (served page 1 again, all known) -> early
    # stop. Pages 1-2 used 2 of the 3 budget pages (the early-stop page is free), so the
    # backfill reads page 4 and stores cursor 5.
    assert _ids(db, "clanky", "fc-news-") == NEWS_IDS | NEWS_PAGE2_IDS
    assert stats.pages == 4
    assert stats.inserted == 5
    assert stats.skipped == 6
    assert client.count(r"/news\?step=96$") == 1
    assert client.count(r"/news\?step=96&page=2$") == 1
    assert client.count(r"/news\?step=96&page=3$") == 1
    assert client.count(r"/news\?step=96&page=4$") == 1
    state = db.get_finecim_sync("news", "ucty")
    assert backfill_position(state) == (5, False)
    assert state["note"].startswith("backfill; after=43566;")  # last card of page 4
    assert state["newest_id"] is None


def test_max_pages_caps_list_pages(db):
    client = FakeClient()
    stats = _syncer(db, client).sync_news(["ucty"], max_pages=1)
    assert stats.pages == 1
    assert client.count(r"page=2") == 0
    assert _ids(db, "clanky", "fc-news-") == NEWS_IDS


def test_full_walks_past_known_pages(db):
    _syncer(db, FakeClient()).sync_news(["ucty"], max_pages=1)
    client = FakeClient(pages={("/ucty/news", 3): EMPTY_LISTING})
    stats = _syncer(db, client).sync_news(["ucty"], max_pages=3, full=True)
    # page 1 is known (no early stop with --full), page 2 is new, page 3 ends the list
    assert stats.pages == 3
    assert stats.inserted == 2  # page 2 only
    assert client.count(r"/news/\d+") == 2
    assert _news_state(db) == (None, True)

def test_max_items_caps_detail_fetches(db):
    client = FakeClient()
    stats = _syncer(db, client).sync_news(["ucty"], max_items=2)
    assert stats.fetched == 2
    assert client.count(r"/news/\d+") == 2
    assert stats.pages == 1
    assert len(_ids(db, "clanky", "fc-news-")) == 2

    client = FakeClient()
    stats = _syncer(db, client).sync_campaigns(["ucty"], max_items=1)
    assert stats.fetched == 1
    assert client.count(r"/campaign/\d+$") == 1
    assert _ids(db, "kampane", "fc-campaign-") == {4695}

    # the next run picks up the remaining items of the page
    client = FakeClient()
    stats = _syncer(db, client).sync_news(["ucty"], max_pages=1)
    assert stats.inserted == 1


def test_updated_badge_triggers_refetch(db):
    _syncer(db, FakeClient()).sync_products(["ucty"])
    html = _fixture("list_products.html").replace(
        '<ul class="ecim-widget-product__badges">',
        '<ul class="ecim-widget-product__badges"><li class="kt-badge">updated</li>',
        1,
    )
    client = FakeClient(overrides={"list_products.html": html})
    stats = _syncer(db, client).sync_products(["ucty"])
    assert client.count(r"/produkt/\d+") == 1
    assert client.count(r"/produkt/3936$") == 1
    assert client.count(r"parameters-new-window/3936") == 1
    assert (stats.fetched, stats.updated, stats.inserted) == (1, 1, 0)
    # the refetch found the same update date: the page needed no real work -> early stop
    # (the remaining budget goes to the backfill pages behind the cursor, not to page 2)
    assert client.count(r"/produkty\?step=96&page=2$") == 0


def test_persistent_product_badge_keeps_early_stop(db):
    html = _fixture("list_products.html").replace(
        '<ul class="ecim-widget-product__badges">',
        '<ul class="ecim-widget-product__badges"><li class="kt-badge">updated</li>',
        1,
    )
    _syncer(db, FakeClient(overrides={"list_products.html": html})).sync_products(["ucty"])
    for _ in range(2):
        client = FakeClient(overrides={"list_products.html": html})
        stats = _syncer(db, client).sync_products(["ucty"])
        assert client.count(r"/produkty\?step=96&page=2$") == 0  # early stop on page 1
        assert client.count(r"/produkt/\d+") == 1
        assert stats.fetched == 1


def test_updated_badge_on_news_triggers_refetch(db):
    _syncer(db, FakeClient()).sync_news(["ucty"], max_pages=1)
    original = _fixture("list_news.html")
    marker = '<li class="kt-badge kt-badge--success kt-badge--inline">new</li>'
    html = original.replace(marker, '<li class="kt-badge kt-badge--success kt-badge--inline">updated</li>', 1)
    assert html != original
    client = FakeClient(overrides={"list_news.html": html})
    stats = _syncer(db, client).sync_news(["ucty"], max_pages=1)
    assert client.count(r"/news/43573$") == 1  # the badged card is refetched
    assert client.count(r"/news/4356[68]$") == 0
    # the badge refetch is not work: page 1 ends the head scan for free and the 1-page
    # budget goes to the backfill (page 2, two new items)
    assert (stats.fetched, stats.updated, stats.inserted) == (3, 1, 2)
    assert client.count(r"/news\?step=96&page=2$") == 1


def test_newer_card_date_triggers_refetch(db):
    _syncer(db, FakeClient()).sync_campaigns(["ucty"])
    html = _fixture("list_campaign.html").replace("aktualizace:</span> 02.11.2026", "aktualizace:</span> 03.11.2026", 1)
    assert html != _fixture("list_campaign.html")
    client = FakeClient(overrides={"list_campaign.html": html})
    stats = _syncer(db, client).sync_campaigns(["ucty"])
    assert client.count(r"/campaign/4695$") == 1
    assert client.count(r"/campaign/\d+$") == 1
    assert stats.updated == 1


def test_parse_error_counts_as_error_and_continues(db):
    client = FakeClient(broken={"/news/43568"})
    stats = _syncer(db, client).sync_news(["ucty"], max_pages=1)
    assert stats.errors == 1
    assert stats.inserted == 2
    assert _ids(db, "clanky", "fc-news-") == NEWS_IDS - {43568}
    state = db.get_finecim_sync("news", "ucty")
    assert state["last_run_at"] and state["last_success_at"] is None
    assert "errors=1" in state["note"]

    # the failed item is retried on the next run
    client = FakeClient()
    stats = _syncer(db, client).sync_news(["ucty"], max_pages=1)
    assert stats.inserted == 1
    assert client.count(r"/news/\d+") == 1


def test_broken_creatives_fragment_skips_the_campaign(db):
    client = FakeClient(broken={"campaign/4686?type"})
    # The fragment parser never raises; a broken fragment just yields no creatives.
    stats = _syncer(db, client).sync_campaigns(["ucty"])
    assert stats.errors == 0
    assert _count(db, "kampane_kreativy", "kampan_id = 'fc-campaign-4686'") == 0


def test_unrelated_campaign_uses_placeholder_competitor(db):
    html = re.sub(
        r'(<div class="[^"]*ecim-widget-basic-links)', r'\1-disabled', _fixture("detail_campaign.html")
    )
    client = FakeClient(overrides={"detail_campaign.html": html})
    _syncer(db, client).sync_campaigns(["ucty"], max_items=1)
    camp = db.conn.execute("SELECT competitor_id FROM kampane WHERE id = 'fc-campaign-4695'").fetchone()
    assert camp["competitor_id"] == FINECIM_PLACEHOLDER_COMPETITOR


def test_all_companies_fetches_unmapped_profiles(db):
    client = FakeClient()
    _syncer(db, client).sync_companies(["ucty"], all_companies=True)
    assert client.count(r"/subjekt/\d+") == 27
    assert db.get_finecim_subject(351)["competitor_id"] == "fc_351"
    assert _count(db, "spolecnost_detail", "competitor_id = 'fc_351'") == 1


def test_summaries_years_refetches_stored_months(db):
    _syncer(db, FakeClient()).sync_summaries(["ucty"])
    client = FakeClient()
    stats = _syncer(db, client).sync_summaries(["ucty"], years=[2026])
    assert stats.fetched == client.count(r"/executive-summary/\d+") > 0
    assert stats.inserted == 0


def test_summaries_years_still_fetches_unstored_months_of_other_years(db):
    client = FakeClient()
    stats = _syncer(db, client).sync_summaries(["ucty"], years=[1999])
    assert stats.inserted > 0
    assert _count(db, "executive_summary", "id = 'fc-es-10664'") == 1


class _AuthFailingClient(FakeClient):
    def get(self, path_or_url: str, *, params: dict | None = None) -> str:
        if "/news/43568" in path_or_url:
            self.requests.append(path_or_url)
            raise FinecimAuthError("session expired and re-login failed")
        return super().get(path_or_url, params=params)


def test_auth_error_mid_segment_records_the_attempt(db):
    with pytest.raises(FinecimAuthError):
        _syncer(db, _AuthFailingClient()).sync_news(["ucty"], max_pages=1)
    state = db.get_finecim_sync("news", "ucty")
    assert state is not None
    assert state["last_run_at"] and state["last_success_at"] is None


def test_unknown_segment_or_entity_raises(db):
    syncer = _syncer(db, FakeClient())
    with pytest.raises(ValueError):
        syncer.sync_news(["nope"])
    with pytest.raises(ValueError):
        syncer.sync_all(["bogus"])


# ── CLI ──────────────────────────────────────────────────────────


@pytest.fixture
def no_credentials(tmp_path, monkeypatch):
    for var in ("FINECIM_USERNAME", "FINECIM_PASSWORD", "FINECIM_ENV_FILE"):
        monkeypatch.delenv(var, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(cred_mod, "REPO_ENV_FILE", tmp_path / "repo" / ".env")
    return home


@pytest.fixture
def cli_config(tmp_path, monkeypatch):
    """A config dir whose settings point the database into tmp_path; logging setup disabled."""
    monkeypatch.setattr(cli_mod, "_setup_logging", lambda level="INFO": None)
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    db_path = tmp_path / "cli.sqlite"
    (config_dir / "settings.yaml").write_text(
        yaml.safe_dump({"database": {"path": str(db_path)}, "finecim": {"schedule": "daily"}}),
        encoding="utf-8",
    )
    for name in ("segments.yaml", "finecim.yaml"):
        (config_dir / name).write_text((CONFIG_DIR / name).read_text(encoding="utf-8"), encoding="utf-8")
    return {"dir": config_dir, "db_path": db_path}


def test_cli_login_check_without_credentials(no_credentials, cli_config):
    result = CliRunner().invoke(cli_mod.cli, ["--config-dir", str(cli_config["dir"]), "finecim", "login-check"])
    assert result.exit_code == 1
    assert "credentials not found" in result.output
    assert "FINECIM_USERNAME" in result.output
    assert ".finecim.env" in result.output
    assert "Traceback" not in result.output
    assert not isinstance(result.exception, Exception) or isinstance(result.exception, SystemExit)


def test_cli_sync_without_credentials(no_credentials, cli_config):
    result = CliRunner().invoke(cli_mod.cli, ["--config-dir", str(cli_config["dir"]), "finecim", "sync"])
    assert result.exit_code == 1
    assert "credentials not found" in result.output


def test_cli_sync_and_status(no_credentials, cli_config, monkeypatch):
    monkeypatch.setenv("FINECIM_USERNAME", "tester")
    monkeypatch.setenv("FINECIM_PASSWORD", "not-a-real-password")
    fake = FakeClient()
    monkeypatch.setattr(cli_mod, "_make_finecim_client", lambda config_dir, creds: fake)
    runner = CliRunner()
    base = ["--config-dir", str(cli_config["dir"])]

    result = runner.invoke(cli_mod.cli, [*base, "finecim", "sync", "--dry-run", "-e", "news"])
    assert result.exit_code == 0, result.output
    assert "dry run" in result.output
    assert fake.requests == []

    db = Database(str(cli_config["db_path"]))
    db.initialize()
    db.seed_segments(str(CONFIG_DIR))
    db.seed_competitors(str(CONFIG_DIR))
    db.close()

    result = runner.invoke(cli_mod.cli, [*base, "finecim", "sync", "-e", "news", "-e", "mystery",
                                         "-s", "ucty", "--max-pages", "1", "--max-items", "2"])
    assert result.exit_code == 0, result.output
    assert "FINeCIM sync" in result.output
    assert "not-a-real-password" not in result.output
    assert fake.count(r"/news/\d+") == 2
    assert fake.count(r"/mystery-shopping/\d+") == 2

    result = runner.invoke(cli_mod.cli, [*base, "finecim", "status"])
    assert result.exit_code == 0, result.output
    assert "FINeCIM sync state" in result.output
    assert "clanky" in result.output
    assert "mystery_shopping" in result.output


def test_cli_status_on_empty_database(cli_config):
    result = CliRunner().invoke(cli_mod.cli, ["--config-dir", str(cli_config["dir"]), "finecim", "status"])
    assert result.exit_code == 0, result.output
    assert "No FINeCIM sync has run yet" in result.output
    assert "FINeCIM data" in result.output


def test_cli_sync_unknown_segment(cli_config, monkeypatch):
    monkeypatch.setenv("FINECIM_USERNAME", "tester")
    monkeypatch.setenv("FINECIM_PASSWORD", "x")
    monkeypatch.setattr(cli_mod, "_make_finecim_client", lambda config_dir, creds: FakeClient())
    result = CliRunner().invoke(
        cli_mod.cli, ["--config-dir", str(cli_config["dir"]), "finecim", "sync", "-s", "nope"]
    )
    assert result.exit_code == 1
    assert "Unknown FINeCIM segment" in result.output


# ── scheduler ────────────────────────────────────────────────────


def test_scheduler_adds_finecim_job_when_credentials_resolve(tmp_config_dir, tmp_path, monkeypatch):
    from src.scheduler import build_scheduler

    monkeypatch.setenv("FINECIM_USERNAME", "tester")
    monkeypatch.setenv("FINECIM_PASSWORD", "x")
    scheduler = build_scheduler(str(tmp_path / "ci.sqlite"), str(tmp_config_dir))
    assert "finecim_sync" in {j.id for j in scheduler.get_jobs()}


def test_scheduler_logs_when_finecim_disabled(tmp_config_dir, tmp_path, no_credentials, caplog):
    from src.scheduler import build_scheduler

    with caplog.at_level("INFO", logger="src.scheduler"):
        scheduler = build_scheduler(str(tmp_path / "ci.sqlite"), str(tmp_config_dir))
    job_ids = {j.id for j in scheduler.get_jobs()}
    assert "finecim_sync" not in job_ids
    assert {"collect_ares", "collect_job_postings", "collect_news"} <= job_ids
    assert any("FINeCIM sync disabled" in r.getMessage() for r in caplog.records)


def test_scheduler_job_uses_the_bounded_default(tmp_config_dir, tmp_path, monkeypatch):
    from src.scheduler import build_scheduler

    monkeypatch.setenv("FINECIM_USERNAME", "tester")
    monkeypatch.setenv("FINECIM_PASSWORD", "x")
    scheduler = build_scheduler(str(tmp_path / "ci.sqlite"), str(tmp_config_dir))
    job = next(j for j in scheduler.get_jobs() if j.id == "finecim_sync")

    calls = []
    monkeypatch.setattr(sync_mod, "client_from_settings", lambda config_dir, creds: FakeClient())
    monkeypatch.setattr(FinecimSync, "sync_all", lambda self, *a, **kw: calls.append(kw) or {})
    job.func()
    assert calls == [{"max_pages": DEFAULT_MAX_PAGES, "max_items": DEFAULT_MAX_ITEMS}]
    assert (DEFAULT_MAX_PAGES, DEFAULT_MAX_ITEMS) == (3, 120)


# ── head scan + resumable backfill ───────────────────────────────


def _news_state(db: Database, segment: str = "ucty") -> tuple[int | None, bool]:
    return backfill_position(db.get_finecim_sync("news", segment))


def test_backfill_resumes_across_runs(db):
    archive = list(range(1000, 970, -1))  # 30 items, 10 pages
    # run 1: budget 1 -> page 1 only, cursor 2
    client, _ = _run_news(db, archive, max_pages=1)
    assert _list_pages_read(client) == [1]
    assert _news_state(db) == (2, False)

    # run 2, again budget 1: page 1 has nothing new (early stop, free), then the backfill
    # reads page 2 -> cursor 3
    client, stats = _run_news(db, archive, max_pages=1)
    assert _list_pages_read(client) == [1, 2]
    assert (stats.pages, stats.inserted) == (2, 3)
    assert _news_state(db) == (3, False)

    # run 3, budget 1: page 1, then page 2 again (known, free: it checks that the page
    # before the cursor still ends at the stored after= id), then page 3 -> cursor 4
    client, _ = _run_news(db, archive, max_pages=1)
    assert _list_pages_read(client) == [1, 2, 3]
    assert _news_state(db) == (4, False)

    # run 4: default budget (3) -> page 1, the check page 3, backfill pages 4, 5 and 6
    client, stats = _run_news(db, archive)
    assert _list_pages_read(client) == [1, 3, 4, 5, 6]
    assert stats.inserted == 3 * DEFAULT_MAX_PAGES
    assert _news_state(db) == (7, False)
    state = db.get_finecim_sync("news", "ucty")
    assert state["last_page"] == 7 and state["note"].startswith("backfill; after=983;")
    assert state["newest_id"] is None

def _renumbered_news_page(offset: int) -> str:
    """list_news.html with every article id shifted by ``offset`` (a page of unseen items)."""
    return re.sub(r"/news/(\d+)", lambda m: f"/news/{int(m.group(1)) + offset}", _fixture("list_news.html"))


def test_first_run_is_bounded_and_later_runs_still_take_new_items_first(db):
    # an empty database where every page holds new articles
    archive = list(range(1000, 970, -1))  # 30 items, 10 pages
    client, stats = _run_news(db, archive)  # no options
    assert stats.pages == DEFAULT_MAX_PAGES
    assert _list_pages_read(client) == [1, 2, 3]  # nothing more
    assert _news_state(db) == (4, False)

    # next run: page 1 has nothing new (early stop, free), page 3 checks the cursor's
    # position (known, free), then backfill pages 4..6
    client, _ = _run_news(db, archive)
    assert _list_pages_read(client) == [1, 3, 4, 5, 6]
    assert _news_state(db) == (7, False)

    # a new article appears on page 1: the head takes it (1 budget page), page 2 has
    # nothing new (early stop), then the backfill continues at 7 for the 2 pages left
    ids = [99999, *archive]
    client, _ = _run_news(db, ids)
    assert client.count(r"/news/99999$") == 1
    assert 99999 in _ids(db, "clanky", "fc-news-")
    assert _list_pages_read(client) == [1, 2, 6, 7, 8]
    assert _news_state(db) == (9, False)

def test_backfill_reaches_the_end_and_completes(db):
    client = FakeClient(pages={("/ucty/news", 3): EMPTY_LISTING})
    stats = _syncer(db, client).sync_news(["ucty"], full=True)  # --full: no budget, no early stop
    assert stats.errors == 0
    assert client.count(r"/news\?") == 3
    assert _news_state(db) == (None, True)
    state = db.get_finecim_sync("news", "ucty")
    assert state["last_page"] is None and state["note"].startswith("complete")

    # complete: the next run reads page 1 only (early stop) and stays complete
    client = FakeClient(pages={("/ucty/news", 3): EMPTY_LISTING})
    stats = _syncer(db, client).sync_news(["ucty"])
    assert client.count(r"/news\?") == 1
    assert client.details() == []
    assert _news_state(db) == (None, True)


def test_list_page_without_last_page_anchor_ends_on_an_empty_page(db):
    html = re.sub(r'<li class="kt-pagination__link--last">.*?</li>', "", _fixture("list_news.html"),
                  flags=re.S)
    html = re.sub(r"Zobrazeno\s+1 - 12 z 4722", "", html)
    assert "kt-pagination__link--last" not in html and "Zobrazeno" not in html
    client = FakeClient(pages={("/ucty/news", 1): html, ("/ucty/news", 2): EMPTY_LISTING})
    stats = _syncer(db, client).sync_news(["ucty"], full=True)
    assert stats.errors == 0
    assert client.count(r"/news\?") == 2  # page 1, then the empty page 2 ends the walk
    assert _news_state(db) == (None, True)


def test_empty_domain_requests_only_first_pages(db):
    client = FakeClient(empty={"/penzijni-spolecnosti/"})
    results = _syncer(db, client).sync_all(segments=["penzijni-spolecnosti"])
    assert sum(s.errors for s in results.values()) == 0
    assert sum(s.fetched for s in results.values()) == 0
    assert client.count(r"page=") == 0
    for path in ("news", "campaign", "mystery-shopping", "produkty"):
        assert client.count(rf"/penzijni-spolecnosti/{path}\?step=96$") == 1
    assert client.count(r"/penzijni-spolecnosti/subjekty$") == 1
    assert client.details() == []
    assert _news_state(db, "penzijni-spolecnosti") == (None, True)


def test_segments_without_products_tab_skip_products(db):
    client = FakeClient()
    stats = _syncer(db, client).sync_products(["fintech", "bankovni-trh"])
    assert client.requests == []
    assert stats.as_dict() == SyncStats().as_dict()
    assert db.get_finecim_sync("product", "fintech") is None

    client = FakeClient()
    _syncer(db, client).sync_all(["product", "news"], ["fintech"], max_pages=1)
    assert client.count(r"/produkty") == 0
    assert client.count(r"/fintech/news\?") == 1


def test_card_linking_to_another_segment_counts_as_known(db):
    _syncer(db, FakeClient()).sync_news(["ucty"], max_pages=1)
    # the sporeni listing shows the same articles, whose links point to the ucty domain
    client = FakeClient()
    syncer = _syncer(db, client)
    html, url = syncer._get_list_page("sporeni", "news", 1)
    assert "/sporeni/news" in url and "/cz/domena/ucty/news/43573" in html
    client.requests.clear()

    stats = syncer.sync_news(["sporeni"], max_pages=2)
    assert client.count(r"/news/43573$|/news/43568$|/news/43566$") == 0  # known: not refetched
    assert stats.skipped >= 3
    # early stop on page 1; the rest of the budget goes to the backfill (page 2)
    assert client.count(r"/sporeni/news\?step=96$") == 1
    assert _count(db, "clanky", "id = 'fc-news-43573' AND segment_id = 'ucty'") == 1
    assert _count(db, "clanky", "segment_id = 'sporeni'") == 0


# ── related subjects ─────────────────────────────────────────────

_UNKNOWN_SUBJECT_ITEM = (
    '<div class="kt-widget4__item"><a href="https://www.finecim.cz/cz/domena/ucty/subjekt/987654" '
    'class="kt-widget4__title">Neznámá finanční s.r.o.</a></div>\n'
)


def _with_unknown_subject_first(fixture: str, anchor: str) -> str:
    html = _fixture(fixture)
    marker = '<div class="kt-widget4__item">'
    index = html.rfind(marker, 0, html.index(anchor))
    assert index > 0
    return html[:index] + _UNKNOWN_SUBJECT_ITEM + html[index:]


def test_first_mapped_related_subject_wins_and_unknown_subjects_get_a_row(db):
    news_html = _with_unknown_subject_first("detail_news.html", "/subjekt/52")
    camp_html = _with_unknown_subject_first("detail_campaign.html", "/subjekt/71")
    client = FakeClient(overrides={"detail_news.html": news_html, "detail_campaign.html": camp_html})
    syncer = _syncer(db, client)
    syncer.sync_news(["ucty"], max_items=1)
    syncer.sync_campaigns(["ucty"], max_items=1)

    news = db.conn.execute("SELECT competitor_id FROM clanky WHERE id = 'fc-news-43573'").fetchone()
    assert news["competitor_id"] == "mbank"  # not None, although the first subject is unmapped
    camp = db.conn.execute("SELECT competitor_id FROM kampane WHERE id = 'fc-campaign-4695'").fetchone()
    assert camp["competitor_id"] == "air_bank"  # not fc_987654
    assert _count(db, "competitors", "id = 'fc_987654'") == 0

    # the unknown subject is still linked, and has a finecim_subjekty row for API joins
    assert _count(db, "finecim_vazby", "subject_id = 987654") == 2
    row = db.get_finecim_subject(987654)
    assert row is not None
    assert row["nazev"] == "Neznámá finanční s.r.o."
    assert row["url"].endswith("/subjekt/987654")
    joined = db.conn.execute(
        """SELECT COUNT(*) FROM finecim_vazby v JOIN finecim_subjekty s ON s.subject_id = v.subject_id
           WHERE v.entity_id IN ('fc-news-43573', 'fc-campaign-4695')"""
    ).fetchone()[0]
    assert joined == 4


def test_only_unmapped_subjects_use_the_first_subject(db):
    html = re.sub(r"/subjekt/71\"", '/subjekt/987654"', _fixture("detail_campaign.html"))
    client = FakeClient(overrides={"detail_campaign.html": html})
    _syncer(db, client).sync_campaigns(["ucty"], max_items=1)
    camp = db.conn.execute("SELECT competitor_id FROM kampane WHERE id = 'fc-campaign-4695'").fetchone()
    assert camp["competitor_id"] == "fc_987654"
    assert db.get_finecim_subject(987654)["competitor_id"] == "fc_987654"


# ── company profiles ─────────────────────────────────────────────


def _age_profile_fetch(db: Database, sid: int, days: int) -> None:
    old = (datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)).isoformat(timespec="seconds")
    db.set_finecim_sync(PROFILE_SYNC_ENTITY, str(sid), last_success_at=old)


def test_profile_refresh_follows_the_profile_age(db):
    client = FakeClient()
    _syncer(db, client).sync_companies(["ucty"])
    first = client.count(r"/subjekt/\d+$")
    assert first > 0
    assert db.get_finecim_sync(PROFILE_SYNC_ENTITY, "71")["last_success_at"]

    # the segment's own last_success_at is fresh after every run; it must not block refreshes
    _age_profile_fetch(db, 71, 8)
    _age_profile_fetch(db, 11, 3)
    client = FakeClient()
    stats = _syncer(db, client).sync_companies(["ucty"])
    assert client.count(r"/subjekt/\d+$") == 1
    assert client.count(r"/subjekt/71$") == 1
    assert stats.fetched == 1
    # ...and the refetch resets the age
    client = FakeClient()
    _syncer(db, client).sync_companies(["ucty"])
    assert client.count(r"/subjekt/\d+$") == 0

    # --full refetches every mapped profile
    client = FakeClient()
    _syncer(db, client).sync_companies(["ucty"], full=True)
    assert client.count(r"/subjekt/\d+$") == first


def test_profile_fallback_url_uses_the_finecim_slug(db):
    client = FakeClient()
    syncer = _syncer(db, client)
    # a segment whose id differs from its FINeCIM slug
    syncer.slug_to_segment["ucty"] = "bankovni-trh"
    syncer._sync_company_profile({"id": 11, "name": "Česká spořitelna"}, "bankovni-trh")
    assert client.requests == ["https://www.finecim.cz/cz/domena/ucty/subjekt/11"]


def test_sync_all_taxonomy_only(db):
    client = FakeClient()
    results = _syncer(db, client).sync_all(["taxonomy"])
    assert set(results) == {"taxonomy"}
    assert len(client.requests) == 10
    assert all(u.endswith("/subjekty") for u in client.requests)
    assert results["taxonomy"].errors == 0


# ── executive summaries ──────────────────────────────────────────


def test_summaries_refresh_the_current_and_previous_month(db):
    _syncer(db, FakeClient()).sync_summaries(["ucty"])
    client = FakeClient()
    syncer = _syncer(db, client)
    syncer.today = lambda: date(2026, 7, 3)  # current = July 2026 (not listed), previous = June
    stats = syncer.sync_summaries(["ucty"])
    assert [u for u in client.requests if "/executive-summary/" in u] == [
        "https://www.finecim.cz/cz/domena/ucty/executive-summary/10664"
    ]
    assert (stats.fetched, stats.inserted) == (1, 0)

    # January: the previous month is December of the year before
    syncer.today = lambda: date(2026, 1, 10)
    assert syncer.recent_summary_months() == {(2026, 1), (2025, 12)}


def test_summary_name_comes_from_the_list_page(db):
    html = _fixture("detail_executive_summary.html").replace(
        '<h1 class="ecim-summary-page__title">červen</h1>', '<h1 class="ecim-summary-page__title">Souhrn</h1>'
    )
    _syncer(db, FakeClient(overrides={"detail_executive_summary.html": html})).sync_summaries(["ucty"])
    es = db.conn.execute("SELECT nazev FROM executive_summary WHERE id = 'fc-es-10677'").fetchone()
    assert es["nazev"] == "květen 2026"


# ── CLI: dry run, taxonomy, status ───────────────────────────────


def _no_client(config_dir, creds):
    raise AssertionError("the dry run must not create a client")


def test_cli_dry_run_needs_no_credentials(no_credentials, cli_config, monkeypatch):
    monkeypatch.setattr(cli_mod, "_make_finecim_client", _no_client)
    base = ["--config-dir", str(cli_config["dir"]), "finecim", "sync", "--dry-run"]
    result = CliRunner().invoke(cli_mod.cli, [*base, "-e", "news", "-s", "ucty"])
    assert result.exit_code == 0, result.output
    assert "dry run" in result.output
    assert "credentials not found" not in result.output
    assert "taxonomy" in result.output and "news" in result.output and "ucty" in result.output
    assert "new (no backfill yet)" in result.output
    assert str(DEFAULT_MAX_PAGES) in result.output
    assert not cli_config["db_path"].exists()  # nothing written

    result = CliRunner().invoke(cli_mod.cli, [*base, "-s", "nope"])
    assert result.exit_code == 1
    assert "Unknown FINeCIM segment" in result.output

    result = CliRunner().invoke(cli_mod.cli, [*base, "-e", "bogus"])
    assert result.exit_code != 0  # click rejects unknown entities

    result = CliRunner().invoke(cli_mod.cli, [*base, "-s", "fintech", "-e", "product", "--full"])
    assert result.exit_code == 0, result.output
    assert "no products tab" in result.output


def test_cli_dry_run_shows_stored_cursors(no_credentials, cli_config, monkeypatch):
    monkeypatch.setattr(cli_mod, "_make_finecim_client", _no_client)
    db = Database(str(cli_config["db_path"]))
    db.initialize()
    db.set_finecim_sync("news", "ucty", last_page=4, note="backfill; fetched=3")
    db.set_finecim_sync("campaign", "ucty", note="complete; fetched=0")
    db.close()
    result = CliRunner().invoke(cli_mod.cli, ["--config-dir", str(cli_config["dir"]), "finecim", "sync",
                                              "--dry-run", "-s", "ucty", "--max-pages", "5"])
    assert result.exit_code == 0, result.output
    assert "backfill from page 4" in result.output
    assert "complete" in result.output
    assert "5" in result.output


def test_cli_sync_unknown_segment_fails_before_login(no_credentials, cli_config, monkeypatch):
    monkeypatch.setattr(cli_mod, "_make_finecim_client", _no_client)
    result = CliRunner().invoke(
        cli_mod.cli, ["--config-dir", str(cli_config["dir"]), "finecim", "sync", "-s", "nope"]
    )
    assert result.exit_code == 1
    assert "Unknown FINeCIM segment" in result.output


def test_cli_taxonomy_entity_and_status_backfill(no_credentials, cli_config, monkeypatch):
    monkeypatch.setenv("FINECIM_USERNAME", "tester")
    monkeypatch.setenv("FINECIM_PASSWORD", "not-a-real-password")
    fake = FakeClient()
    monkeypatch.setattr(cli_mod, "_make_finecim_client", lambda config_dir, creds: fake)
    db = Database(str(cli_config["db_path"]))
    db.initialize()
    db.seed_segments(str(CONFIG_DIR))
    db.seed_competitors(str(CONFIG_DIR))
    db.close()
    runner = CliRunner()
    base = ["--config-dir", str(cli_config["dir"]), "finecim"]

    result = runner.invoke(cli_mod.cli, [*base, "sync", "-e", "taxonomy"])
    assert result.exit_code == 0, result.output
    assert fake.requests and all(u.endswith("/subjekty") for u in fake.requests)
    assert "taxonomy" in result.output

    result = runner.invoke(cli_mod.cli, [*base, "sync", "-e", "news", "-s", "ucty", "--max-pages", "1"])
    assert result.exit_code == 0, result.output
    db = Database(str(cli_config["db_path"]))
    db.set_finecim_sync("mystery", "ucty", note="complete; fetched=0")
    db.close()

    result = runner.invoke(cli_mod.cli, [*base, "status"])
    assert result.exit_code == 0, result.output
    assert "Backfill" in result.output
    assert "next page 2" in result.output
    assert "complete" in result.output

# ── an interrupted head keeps the cursor / complete state ─────────

_ORIG_NEWS_ON_PAGE1 = (43573, 43568, 43566)


def _synthetic_news_lists(ids: list[int], segment: str = "ucty") -> dict[tuple[str, int], str]:
    """A news list of ``ids`` (newest first), 3 cards per page, then an empty page."""
    base = _fixture("list_news.html")

    def page_html(chunk: list[int]) -> str:
        html = base
        for old, new in zip(_ORIG_NEWS_ON_PAGE1, (chunk * 3)[:3], strict=True):
            html = html.replace(f"news/{old}", f"news/{new}")
        return html

    pages = {(f"/{segment}/news", i // 3 + 1): page_html(ids[i:i + 3]) for i in range(0, len(ids), 3)}
    pages[(f"/{segment}/news", (len(ids) + 2) // 3 + 1)] = EMPTY_LISTING
    return pages


def _list_pages_read(client: FakeClient) -> list[int]:
    out = []
    for url in client.requests:
        if re.search(r"/news\?", url):
            m = re.search(r"page=(\d+)", url)
            out.append(int(m.group(1)) if m else 1)
    return out


def _run_news(db: Database, ids: list[int], **kw) -> tuple[FakeClient, SyncStats]:
    client = FakeClient(pages=_synthetic_news_lists(ids))
    stats = _syncer(db, client).sync_news(["ucty"], **kw)
    return client, stats


def test_capped_head_on_a_complete_list_keeps_it_complete(db):
    archive = list(range(1000, 970, -1))  # 30 items, 10 pages
    _run_news(db, archive, full=True)
    assert _news_state(db) == (None, True)

    ids = [2001, 2000, *archive]  # two new items on top
    client, stats = _run_news(db, ids, max_items=1)
    assert stats.fetched == 1
    assert _news_state(db) == (None, True)  # still complete, no cursor
    # the guard is the first card not fetched: no early stop before passing it
    assert resume_state(db.get_finecim_sync("news", "ucty")).guard == 2000

    # next plain run: the head picks up the second new item, then stops early
    client, stats = _run_news(db, ids)
    assert stats.fetched == 1
    assert _list_pages_read(client) == [1, 2]
    assert _news_state(db) == (None, True)
    assert db.get_finecim_sync("news", "ucty")["newest_id"] is None

    client, stats = _run_news(db, ids)
    assert (_list_pages_read(client), stats.fetched) == ([1], 0)

def test_burst_filling_the_budget_continues_the_head_not_the_archive(db):
    archive = list(range(1000, 970, -1))
    _run_news(db, archive, full=True)

    # 12 new items = 4 pages, more than the 3-page budget
    ids = [*range(3011, 2999, -1), *archive]
    client, stats = _run_news(db, ids)
    assert _list_pages_read(client) == [1, 2, 3]
    assert stats.fetched == 9
    assert _news_state(db) == (None, True)
    state = db.get_finecim_sync("news", "ucty")
    assert state["newest_id"] == 3003 and state["note"].startswith("complete")  # last card of page 3

    # next run: pages 1..3 are known but not below the guard (free, no early stop), page 4
    # has the 3 remaining items, page 5 is old and below the guard (early stop); the list
    # stays complete: no walk through the archive
    client, stats = _run_news(db, ids)
    assert _list_pages_read(client) == [1, 2, 3, 4, 5]
    assert stats.fetched == 3
    assert {i for i in range(3000, 3012)} <= _ids(db, "clanky", "fc-news-")
    assert _news_state(db) == (None, True)
    assert db.get_finecim_sync("news", "ucty")["newest_id"] is None

    client, stats = _run_news(db, ids)
    assert (_list_pages_read(client), stats.fetched) == ([1], 0)

def test_capped_head_does_not_move_a_backfill_cursor_back(db):
    archive = list(range(1000, 970, -1))
    _run_news(db, archive, max_pages=3)
    _run_news(db, archive, max_pages=3)
    assert _news_state(db) == (7, False)

    ids = [2001, 2000, *archive]
    client, stats = _run_news(db, ids, max_items=1)
    assert _news_state(db) == (7, False)  # cursor kept
    assert db.get_finecim_sync("news", "ucty")["newest_id"] == 2000  # the head guard

    # next run: page 1 takes the other new item, page 2 stops the head, the check page 6,
    # then backfill 7 and 8 (page 7 starts with two known items shifted down by the new ones)
    client, stats = _run_news(db, ids)
    assert _list_pages_read(client) == [1, 2, 6, 7, 8]
    assert _news_state(db) == (9, False)
    assert db.get_finecim_sync("news", "ucty")["newest_id"] is None

def test_status_label_shows_an_unfinished_head():
    assert cli_mod._backfill_label(None, True, short=True, guard=4) == "complete, head unfinished (guard id 4)"
    assert cli_mod._backfill_label(7, False, short=True) == "next page 7"

def test_named_schedules_run_in_utc():
    from src.scheduler import parse_trigger

    assert str(parse_trigger("daily").timezone) == "UTC"
    assert str(parse_trigger("15 4 * * *").timezone) == "UTC"


# ── review fixes: overlapping head resumes, profile counts, read-only dry run ──


def test_two_bursts_over_budget_in_a_row_lose_nothing(db):
    archive = list(range(1000, 970, -1))  # 30 items, 10 pages
    _run_news(db, archive, full=True)
    burst1 = list(range(3011, 2999, -1))  # 12 items = 4 pages > the 3-page budget
    ids = [*burst1, *archive]
    _run_news(db, ids)
    assert db.get_finecim_sync("news", "ucty")["newest_id"] == 3003

    # a second over-budget burst before burst 1's tail was fetched: the older (smaller)
    # guard is kept, so no early stop happens before burst 1's tail
    ids = [*range(4011, 3999, -1), *ids]
    client, stats = _run_news(db, ids)
    assert _list_pages_read(client) == [1, 2, 3]
    state = db.get_finecim_sync("news", "ucty")
    assert state["newest_id"] == 3003
    assert state["note"].startswith("complete")

    # one plain run takes both tails: 2 budget pages, the known pages in between are free
    client, stats = _run_news(db, ids)
    assert stats.fetched == 6
    assert set(ids) <= _ids(db, "clanky", "fc-news-")
    assert db.get_finecim_sync("news", "ucty")["newest_id"] is None
    assert _news_state(db) == (None, True)
    client, stats = _run_news(db, ids)
    assert (_list_pages_read(client), stats.fetched) == ([1], 0)

def test_capped_run_while_a_head_guard_is_pending_loses_nothing(db):
    archive = list(range(1000, 970, -1))
    _run_news(db, archive, full=True)
    ids = [*range(3011, 2999, -1), *archive]
    _run_news(db, ids)
    assert db.get_finecim_sync("news", "ucty")["newest_id"] == 3003

    # a capped smoke run with two new items on top stops on page 1; the older guard stays
    ids = [5001, 5000, *ids]
    client, stats = _run_news(db, ids, max_items=1)
    assert stats.fetched == 1
    assert db.get_finecim_sync("news", "ucty")["newest_id"] == 3003

    for _ in range(2):
        _run_news(db, ids)
    assert set(ids) <= _ids(db, "clanky", "fc-news-")
    assert _news_state(db) == (None, True)
    assert db.get_finecim_sync("news", "ucty")["newest_id"] is None

def test_resume_state_round_trips_through_the_row():
    row = {"last_page": 5, "newest_id": 9, "note": "backfill; after=77; retry=2; fetched=0"}
    st = resume_state(row)
    assert (st.cursor, st.complete, st.guard, st.after, st.retry) == (5, False, 9, 77, 2)
    assert st.note_prefix() == "backfill; after=77; retry=2; "
    st = resume_state({"last_page": None, "newest_id": None, "note": "complete; fetched=0"})
    assert (st.cursor, st.complete, st.guard) == (None, True, None)
    assert st.note_prefix() == "complete; "
    assert resume_state(None) == sync_mod.ResumeState()
    assert resume_state(None).note_prefix() == "head; "
    label = cli_mod._backfill_label(5, False, guard=9)
    assert label == "backfill from page 5, head unfinished (guard id 9)"

def test_first_profile_fetch_counts_as_inserted(db):
    stats = _syncer(db, FakeClient()).sync_companies(["ucty"])
    assert stats.fetched > 0
    # inserted also counts the new /subjekty rows; no profile existed, so nothing is "updated"
    assert stats.inserted >= stats.fetched and stats.updated == 0
    stats = _syncer(db, FakeClient()).sync_companies(["ucty"], full=True)
    assert stats.fetched > 0
    assert stats.updated == stats.fetched and stats.inserted == 0


def test_cli_dry_run_opens_the_database_read_only(no_credentials, cli_config, monkeypatch):
    import sqlite3

    monkeypatch.setattr(cli_mod, "_make_finecim_client", _no_client)
    db = Database(str(cli_config["db_path"]))
    db.initialize()
    db.set_finecim_sync("news", "ucty", last_page=4, note="backfill; fetched=3")
    db.conn.execute("PRAGMA journal_mode=DELETE")
    db.close()
    before = cli_config["db_path"].read_bytes()

    def _no_database(*a, **kw):
        raise AssertionError("the dry run must not open a writable Database")

    monkeypatch.setattr(cli_mod, "Database", _no_database)
    result = CliRunner().invoke(cli_mod.cli, ["--config-dir", str(cli_config["dir"]), "finecim", "sync",
                                              "--dry-run", "-s", "ucty", "-e", "news"])
    assert result.exit_code == 0, result.output
    assert "backfill from page 4" in result.output
    assert cli_config["db_path"].read_bytes() == before
    conn = sqlite3.connect(str(cli_config["db_path"]))
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        conn.close()


# ── crash-safe checkpoints ───────────────────────────────────────


class _CrashClient(FakeClient):
    """FakeClient whose ``crash_at``-th news detail request raises ``exc`` (after calling
    ``on_crash``, which may snapshot the database as a killed process would leave it)."""

    def __init__(self, *a, crash_at: int, exc: BaseException, on_crash=None, **kw):
        super().__init__(*a, **kw)
        self.crash_at, self.exc, self.on_crash = crash_at, exc, on_crash
        self.news_details = 0

    def get(self, path_or_url: str, *, params: dict | None = None) -> str:
        if re.search(r"/news/\d+$", urlsplit(path_or_url).path):
            self.news_details += 1
            if self.news_details == self.crash_at:
                self.requests.append(path_or_url)
                if self.on_crash is not None:
                    self.on_crash()
                raise self.exc
        return super().get(path_or_url, params=params)


def _disk_snapshot(db: Database, dest: Path) -> None:
    """What is committed on disk right now (read through a separate connection)."""
    import sqlite3

    src = sqlite3.connect(db.db_path)
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()


_ARCHIVE = list(range(1000, 970, -1))   # 30 items, 10 pages of 3
_BURST = list(range(2008, 1999, -1))    # 9 new items = 3 pages: [2008..2006] [2005..2003] [2002..2000]


@pytest.mark.parametrize("mode", ["kill", "interrupt", "caught"])
def test_crash_on_the_fifth_detail_of_a_burst_loses_nothing(db, tmp_path, mode):
    _run_news(db, _ARCHIVE, full=True)
    assert _news_state(db) == (None, True)
    ids = [*_BURST, *_ARCHIVE]
    snapshot = tmp_path / "killed.sqlite"
    exc = KeyboardInterrupt() if mode == "interrupt" else RuntimeError("boom")
    client = _CrashClient(pages=_synthetic_news_lists(ids), crash_at=5, exc=exc,
                          on_crash=(lambda: _disk_snapshot(db, snapshot)) if mode == "kill" else None)
    if mode == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            _syncer(db, client).sync_news(["ucty"])
    else:
        _syncer(db, client).sync_news(["ucty"])  # a RuntimeError in a detail is a failed detail
    target = db
    if mode == "kill":
        # a killed process writes nothing more: continue from what was on disk at the crash
        target = Database(str(snapshot))
        assert _ids(target, "clanky", "fc-news-") >= {2008, 2007, 2006, 2005}
        assert 2004 not in _ids(target, "clanky", "fc-news-")
        st = resume_state(target.get_finecim_sync("news", "ucty"))
        # written before page 2's details were fetched: its smallest new card
        assert st.complete and st.guard == 2003
    try:
        for _ in range(4):
            _run_news(target, ids)
        assert set(ids) <= _ids(target, "clanky", "fc-news-")
        st = resume_state(target.get_finecim_sync("news", "ucty"))
        assert st.complete and st.guard is None
        client, stats = _run_news(target, ids)
        assert (_list_pages_read(client), stats.fetched) == ([1], 0)
    finally:
        if target is not db:
            target.close()


def test_kill_during_a_first_run_resumes_through_the_cursor(db, tmp_path):
    archive = list(range(1000, 970, -1))
    snapshot = tmp_path / "killed.sqlite"
    client = _CrashClient(pages=_synthetic_news_lists(archive), crash_at=8, exc=RuntimeError("x"),
                          on_crash=lambda: _disk_snapshot(db, snapshot))
    _syncer(db, client).sync_news(["ucty"])
    killed = Database(str(snapshot))
    try:
        st = resume_state(killed.get_finecim_sync("news", "ucty"))
        assert st.cursor == 3 and not st.complete  # page 3 had started: the backfill re-reads it
        for _ in range(6):
            _run_news(killed, archive)
        assert set(archive) <= _ids(killed, "clanky", "fc-news-")
        assert _news_state(killed) == (None, True)
    finally:
        killed.close()


@pytest.mark.parametrize("where", ["page-lookup", "detail-write"])
def test_database_error_mid_walk_loses_nothing(db, monkeypatch, where):
    import sqlite3

    _run_news(db, _ARCHIVE, full=True)
    ids = [*_BURST, *_ARCHIVE]
    calls = {"n": 0}
    method = "known_finecim_ids" if where == "page-lookup" else "upsert_clanek"
    real = getattr(db, method)
    fail_on = 2 if where == "page-lookup" else 5   # page 2's lookup / the 5th detail write

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == fail_on:
            raise sqlite3.OperationalError("database is locked")
        return real(*a, **kw)

    monkeypatch.setattr(db, method, flaky)
    if where == "page-lookup":
        with pytest.raises(sqlite3.OperationalError):
            _run_news(db, ids)
        st = resume_state(db.get_finecim_sync("news", "ucty"))
        assert st.complete and st.guard == 2006  # page 1 was finished
    else:
        _, stats = _run_news(db, ids)  # inside a detail: a failed detail, the run goes on
        assert stats.errors == 1
    monkeypatch.setattr(db, method, real)
    for _ in range(4):
        _run_news(db, ids)
    assert set(ids) <= _ids(db, "clanky", "fc-news-")
    st = resume_state(db.get_finecim_sync("news", "ucty"))
    assert st.complete and st.guard is None


def test_checkpoints_are_written_per_page(db, monkeypatch):
    writes = []
    real = db.set_finecim_sync
    monkeypatch.setattr(db, "set_finecim_sync",
                        lambda entity, seg, **f: (writes.append(dict(f)), real(entity, seg, **f))[1])
    _run_news(db, _ARCHIVE)  # first run: head pages 1..3 (budget 3), then cursor 4
    assert len(writes) >= 3
    # the first write precedes any detail fetch: the cursor at page 1
    assert writes[0]["last_page"] == 1
    assert writes[-1]["last_page"] == 4 and "last_success_at" in writes[-1]
    assert all("last_success_at" not in w for w in writes[:-1])


# ── markup-change safety ─────────────────────────────────────────

_NO_CONTAINER = '<html><body><div id="kt_content"><div class="new-layout"><p>Zprávy</p></div></div></body></html>'


def _resume_tuple(db: Database) -> tuple:
    st = resume_state(db.get_finecim_sync("news", "ucty"))
    return st.cursor, st.complete, st.guard, st.after, st.retry


@pytest.mark.parametrize("page", [1, 4])
def test_missing_listing_container_is_an_error_and_keeps_the_state(db, page):
    _run_news(db, _ARCHIVE)  # pages 1..3, cursor 4
    before = _resume_tuple(db)
    assert before[0] == 4 and not before[1]
    pages = _synthetic_news_lists(_ARCHIVE)
    pages[("/ucty/news", page)] = _NO_CONTAINER
    client = FakeClient(pages=pages)
    stats = _syncer(db, client).sync_news(["ucty"])
    assert stats.errors == 1
    assert _resume_tuple(db) == before  # no completion, cursor and guard untouched
    # the markup is back: the walk continues where it was
    _, stats = _run_news(db, _ARCHIVE)
    assert stats.errors == 0 and _news_state(db) == (7, False)


def test_missing_listing_container_in_the_head_keeps_a_pending_guard(db):
    _run_news(db, _ARCHIVE, full=True)
    db.set_finecim_sync("news", "ucty", newest_id=_ARCHIVE[-1])  # a pending guard far below
    pages = _synthetic_news_lists(_ARCHIVE)
    pages[("/ucty/news", 2)] = _NO_CONTAINER
    stats = _syncer(db, FakeClient(pages=pages)).sync_news(["ucty"])
    assert stats.errors == 1
    st = resume_state(db.get_finecim_sync("news", "ucty"))
    assert st.complete and st.guard == _ARCHIVE[-1]


@pytest.mark.parametrize("failure", ["raises", "cards-without-ids"])
def test_list_parser_failure_is_an_error_and_keeps_the_state(db, monkeypatch, failure):
    _run_news(db, _ARCHIVE)
    before = _resume_tuple(db)
    path, real_parser, entity_type = sync_mod._LIST_ENTITIES["news"]

    def parser(html, url):
        if "<!-- changed -->" not in html:
            return real_parser(html, url)
        if failure == "raises":
            raise ValueError("unexpected markup")
        return [{"id": None, "url": url, "title": "?"}]

    monkeypatch.setitem(sync_mod._LIST_ENTITIES, "news", (path, parser, entity_type))
    pages = _synthetic_news_lists(_ARCHIVE)
    pages[("/ucty/news", 4)] = "<!-- changed -->" + pages[("/ucty/news", 4)]
    stats = _syncer(db, FakeClient(pages=pages)).sync_news(["ucty"])
    assert stats.errors == 1
    assert _resume_tuple(db) == before


def test_page_beyond_the_pagers_last_page_ends_the_list(db):
    ids = list(range(1008, 999, -1))  # 3 pages
    pages = _synthetic_news_lists(ids)
    # the site answers page 3 with a footer whose total ends before it
    # (its pager links end at page 2)
    pages[("/ucty/news", 3)] = re.sub(r"page=\d+", "page=2", pages[("/ucty/news", 3)]).replace("z 4722", "z 6")
    client = FakeClient(pages=pages)
    stats = _syncer(db, client).sync_news(["ucty"], full=True)
    assert stats.errors == 0
    assert _list_pages_read(client) == [1, 2, 3]  # page 4 (empty) is never requested
    assert _news_state(db) == (None, True)


def test_existing_empty_container_ends_the_list(db):
    client = FakeClient(pages={("/ucty/news", 1): EMPTY_LISTING})
    stats = _syncer(db, client).sync_news(["ucty"])
    assert (stats.errors, stats.fetched) == (0, 0)
    assert _news_state(db) == (None, True)


# ── executive summaries: titles and entry links ──────────────────


def test_summary_title_from_the_month_number():
    assert sync_mod.summary_title("červen", 6, 2026) == "červen 2026"
    assert sync_mod.summary_title("6/2014 Executive Summary", 6, 2014) == "červen 2014"
    assert sync_mod.summary_title("12/2019 Executive Summary", 12, 2019) == "prosinec 2019"
    assert sync_mod.summary_title(None, 1, 2018) == "leden 2018"


def _synthetic_summary(monkeypatch, label: str, year: int, month: int, entries: list[dict]) -> None:
    from src.finecim import parsers

    url = "https://www.finecim.cz/cz/domena/ucty/executive-summary/777"
    monkeypatch.setattr(parsers, "parse_executive_summary_list", lambda html, u: [
        {"id": 777, "url": url, "segment": "ucty", "year": year, "month": month, "month_name": label},
    ])
    monkeypatch.setattr(parsers, "parse_executive_summary_detail", lambda html, u: {
        "id": 777, "url": url, "segment": "ucty", "month_name": None, "entries": entries,
    })


def test_pre_2020_summary_gets_a_czech_month_title(db, monkeypatch):
    _synthetic_summary(monkeypatch, "6/2014 Executive Summary", 2014, 6, [])
    stats = _syncer(db, FakeClient()).sync_summaries(["ucty"])
    assert stats.errors == 0
    row = db.conn.execute("SELECT nazev, rok, mesic FROM executive_summary WHERE id = 'fc-es-777'").fetchone()
    assert (row["nazev"], row["rok"], row["mesic"]) == ("červen 2014", 2014, 6)


def test_summary_entries_store_link_type_and_url(db, monkeypatch):
    base = "https://www.finecim.cz/cz/domena/ucty"
    entries = [
        {"entry_id": 1, "title": "Zpráva", "text": "a", "entity": "news", "news_id": 42,
         "news_url": f"{base}/news/42", "item_url": f"{base}/news/42"},
        {"entry_id": 2, "title": "Kampaň", "text": "b", "entity": "campaign", "news_id": None,
         "news_url": None, "item_url": f"{base}/campaign/4695"},
        {"entry_id": 3, "title": "Produkt", "text": "c", "entity": "produkt", "news_id": None,
         "news_url": None, "item_url": f"{base}/produkt/3936"},
        {"entry_id": 4, "title": "Bez odkazu", "text": "d", "entity": None, "news_id": None,
         "news_url": None, "item_url": None},
        # an entry from a parser without the entity key: a news id still links the article
        {"entry_id": 5, "title": "Starší", "text": "e", "news_id": 7, "news_url": f"{base}/news/7"},
    ]
    _synthetic_summary(monkeypatch, "červen", 2026, 6, entries)
    captured = []
    real = db.upsert_executive_summary
    monkeypatch.setattr(db, "upsert_executive_summary",
                        lambda row, polozky: (captured.append(polozky), real(row, polozky))[1])
    _syncer(db, FakeClient()).sync_summaries(["ucty"])
    polozky = {p["id"]: p for p in captured[0]}
    expected = {
        "fc-es-entry-1": ("fc-news-42", f"{base}/news/42", "news"),
        "fc-es-entry-2": (None, f"{base}/campaign/4695", "campaign"),
        "fc-es-entry-3": (None, f"{base}/produkt/3936", "produkt"),
        "fc-es-entry-4": (None, None, None),
        "fc-es-entry-5": ("fc-news-7", f"{base}/news/7", "news"),
    }
    assert {k: (p["clanek_id"], p["url"], p["typ"]) for k, p in polozky.items()} == expected
    telo = db.conn.execute("SELECT telo FROM executive_summary WHERE id = 'fc-es-777'").fetchone()["telo"]
    assert f"- [Kampaň]({base}/campaign/4695): b" in telo
    assert "- Bez odkazu: d" in telo
    columns = {r["name"] for r in db.conn.execute("PRAGMA table_info(executive_summary_polozky)")}
    if {"url", "typ"} <= columns:  # stored once the schema has the columns
        rows = db.conn.execute(
            "SELECT id, clanek_id, url, typ FROM executive_summary_polozky WHERE summary_id = 'fc-es-777'"
        ).fetchall()
        assert {r["id"]: (r["clanek_id"], r["url"], r["typ"]) for r in rows} == expected
