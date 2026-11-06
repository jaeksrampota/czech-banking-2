"""Digest generator: period maths, sections of the digest, renderers, CLI and API route."""

from datetime import date
from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner
from src import cli as cli_mod
from src.api import create_app
from src.digest import (
    Period,
    build_digest,
    compute_period,
    diff_atributy,
    digest_filename,
    format_date_cz,
    rank_by_tier,
    render_html,
    render_markdown,
    write_digest,
)
from src.digest.render import EMPTY_ALL, EMPTY_MARKET, EMPTY_SUMMARIES, SECTION_TITLES, plural_cz
from src.models.database import FINECIM_PLACEHOLDER_COMPETITOR, Database

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"
FC = "https://www.finecim.cz/cz/domena"
UNTIL = "2026-11-06"  # weekly period 2026-10-31 .. 2026-11-06, monthly 2026-10-07 .. 2026-11-06


# ── fixtures ─────────────────────────────────────────────────────


def _news(db: Database, n: int, competitor: str | None, segment: str, datum: str, typ: str | None = "tiskové zprávy",
          **over) -> None:
    row = {
        "id": f"fc-news-{n}", "competitor_id": competitor, "segment_id": segment, "nazev": f"Zpráva {n}",
        "datum": datum, "typ_zpravy": typ, "stav": "new", "perex": f"Perex {n}", "telo": "<p>t</p>",
        "tagy": ["tag"], "url": f"{FC}/{segment}/news/{n}",
    }
    row.update(over)
    db.upsert_clanek(row)


def seed_digest_rows(db: Database) -> None:
    """Rows around the weekly period 2026-10-31..2026-11-06 (tiers from config: ČS/ČSOB 1, mBank 2)."""
    # news: boundaries, market-level (no competitor / Bankovní trh domain)
    _news(db, 1, "mbank", "ucty", "2026-11-05", "produkty a služby, tiskové zprávy",
          nazev="mBank mění ceník", tagy=["mBank", "poplatky"])
    _news(db, 2, "ceska_sporitelna", "ucty", "2026-10-31", nazev="ČS [novinka] | start")   # period start
    _news(db, 3, "ceska_sporitelna", "ucty", "2026-10-30")                                 # day before
    _news(db, 4, "csob", "hypoteky", "2026-11-06", "hypotéky")                            # period end
    _news(db, 5, "csob", "hypoteky", "2026-11-07")                                         # day after
    _news(db, 6, None, "ucty", "2026-11-03", "regulace", nazev="ČNB sazby")                # market: no company
    _news(db, 7, "csob", "bankovni-trh", "2026-11-04", None, nazev="ČSOB na trhu", url=None,
          perex=None)                                                                      # market: domain

    # campaigns: started in period, updated in period, outside
    db.upsert_kampan({
        "id": "fc-campaign-900", "competitor_id": "ceska_sporitelna", "segment_id": "ucty",
        "nazev": "Kampaň George", "zacatek": "2026-11-02", "aktualizace": None, "popis": "Anotace kampaně",
        "media_typy": ["TV", "Web"], "typ_kampane": "Produktová, Imageová",
        "kreativa_url": "https://www.finecim.cz/media/image/default/1",
    })
    db.replace_kampan_kreativy("fc-campaign-900", [
        {"id": "fc-creative-2", "datum": "2026-11-03", "media_typ": "Web", "popis": "Banner",
         "media_url": "https://www.finecim.cz/media/image/default/11", "media_druh": "image"},
        {"id": "fc-creative-1", "datum": "2026-11-02", "media_typ": "TV", "popis": "Spot",
         "media_url": "https://www.finecim.cz/media/download/default/10", "media_druh": "video"},
    ])
    db.upsert_kampan({
        "id": "fc-campaign-901", "competitor_id": "mbank", "segment_id": "sporeni", "nazev": "mKonto",
        "zacatek": "2026-09-01", "aktualizace": "2026-11-05", "popis": None, "media_typy": ["Social"],
        "typ_kampane": None, "kreativa_url": None,
    })
    db.upsert_kampan({
        "id": "fc-campaign-902", "competitor_id": "mbank", "segment_id": "ucty", "nazev": "Stará",
        "zacatek": "2026-09-01", "aktualizace": "2026-10-01", "media_typy": [],
    })

    # products: changed (two versions), new, updated without a previous version, outside
    base77 = {
        "id": "fc-product-77", "competitor_id": "ceska_sporitelna", "segment_id": "ucty",
        "produktova_linie_id": "ucty__mobilni_aplikace", "zakaznicky_segment": "Fyzické osoby",
        "nazev": "George", "kratky_popis": "Mobilní bankovnictví", "url": f"{FC}/ucty/produkt/77", "aktivni": 1,
    }
    db.upsert_produkt({
        **base77, "aktualizace": "2026-10-01", "pridano_at": "2026-10-01T10:00:00",
        "atributy": [
            {"section": "Aktuální verze", "name": "iOS (verze)", "value": "26.4.51"},
            {"section": "Aktuální verze", "name": "Android (verze)", "value": "7.1"},
            {"section": "Funkce", "name": "Apple Pay", "value": "ano"},
        ],
    })
    db.upsert_produkt({
        **base77, "aktualizace": "2026-11-04",
        "atributy": [
            {"section": "Aktuální verze", "name": "iOS (verze)", "value": "26.5.0"},
            {"section": "Aktuální verze", "name": "Android (verze)", "value": " 7.1 "},
            {"section": "Funkce", "name": "Google Pay", "value": "ano"},
        ],
    })
    db.upsert_produkt({
        "id": "fc-product-78", "competitor_id": "mbank", "segment_id": "ucty", "nazev": "mKonto Plus",
        "kratky_popis": "Účet", "atributy": [{"section": None, "name": "Poplatek", "value": "0 Kč"}],
        "url": f"{FC}/ucty/produkt/78", "aktivni": 1, "aktualizace": "2026-11-05",
        "pridano_at": "2026-11-05T09:00:00",
    })
    db.upsert_produkt({
        "id": "fc-product-79", "competitor_id": "csob", "segment_id": "ucty", "nazev": "Plus konto",
        "atributy": [], "url": f"{FC}/ucty/produkt/79", "aktivni": 1, "aktualizace": "2026-11-02",
        "pridano_at": "2026-01-01T00:00:00",
    })
    db.upsert_produkt({
        "id": "fc-product-80", "competitor_id": "csob", "segment_id": "ucty", "nazev": "Staré konto",
        "atributy": [], "aktivni": 1, "aktualizace": "2026-10-01", "pridano_at": "2026-01-01T00:00:00",
    })

    # mystery shopping: with pdf, without company (pdf from attachments), outside
    db.upsert_mystery({
        "id": "fc-ms-5", "competitor_id": "ceska_sporitelna", "segment_id": "ucty", "nazev": "MS onboarding",
        "datum": "2026-11-06", "popis": "Perex\n\nText", "pdf_url": "https://www.finecim.cz/media/pdf/open?itemId=5",
    })
    db.upsert_mystery({
        "id": "fc-ms-6", "competitor_id": None, "segment_id": "ucty", "nazev": "MS bez firmy",
        "datum": "2026-10-31", "popis": None, "pdf_url": None,
    })
    db.replace_prilohy("mystery", "fc-ms-6", [
        {"name": "Zpráva", "url": "https://www.finecim.cz/media/pdf/open?itemId=6"},
    ])
    db.upsert_mystery({
        "id": "fc-ms-7", "competitor_id": "ceska_sporitelna", "segment_id": "ucty", "nazev": "Stará MS",
        "datum": "2026-10-01",
    })

    # executive summaries: November (in), October (overlaps 31. 10.), September (out)
    db.upsert_executive_summary(
        {"id": "fc-es-12", "segment_id": "ucty", "rok": 2026, "mesic": 11, "nazev": "listopad 2026",
         "telo": "-", "pdf_url": None},
        [{"entry_id": 101, "clanek_id": "fc-news-1", "nazev": "mBank mění ceník", "text": "Shrnutí 1",
          "url": f"{FC}/ucty/news/1", "typ": "news"},
         {"entry_id": 102, "clanek_id": None, "nazev": "Kampaň", "text": "Shrnutí 2",
          "url": f"{FC}/ucty/campaign/900", "typ": "campaign"}],
    )
    db.upsert_executive_summary(
        {"id": "fc-es-10", "segment_id": "hypoteky", "rok": 2026, "mesic": 10, "nazev": "říjen 2026"}, [])
    db.upsert_executive_summary(
        {"id": "fc-es-11", "segment_id": "sporeni", "rok": 2026, "mesic": 9, "nazev": "září 2026"}, [])


@pytest.fixture
def db_path(tmp_path) -> str:
    """A seeded database (repo config: 10 segments, 19 competitors) with the rows above; closed."""
    database = Database(str(tmp_path / "digest.sqlite"))
    database.initialize()
    database.seed_segments(str(CONFIG_DIR))
    database.seed_competitors(str(CONFIG_DIR))
    seed_digest_rows(database)
    database.close()
    return str(tmp_path / "digest.sqlite")


@pytest.fixture
def db(db_path) -> Database:
    database = Database(db_path)
    yield database
    database.close()


@pytest.fixture
def weekly(db) -> dict:
    return build_digest(db, compute_period("weekly", UNTIL))


def _company(digest: dict, competitor_id: str) -> dict:
    return next(c for c in digest["spolecnosti"] if c["id"] == competitor_id)


def _news_ids(company: dict) -> list[str]:
    return [item["id"] for group in company["zpravy"] for item in group["polozky"]]


# ── period ───────────────────────────────────────────────────────


def test_compute_period_weekly_and_monthly():
    weekly = compute_period("weekly", UNTIL)
    assert (weekly.od, weekly.do, weekly.typ) == (date(2026, 10, 31), date(2026, 11, 6), "weekly")
    monthly = compute_period("monthly", date(2026, 11, 6))
    assert (monthly.od, monthly.do) == (date(2026, 10, 7), date(2026, 11, 6))
    assert compute_period("monthly", "2026-03-31").od == date(2026, 3, 1)
    assert compute_period("monthly", "2026-03-01").od == date(2026, 2, 2)
    assert compute_period("weekly").do == date.today()
    assert compute_period("weekly", "2026-11-06T12:00:00").do == date(2026, 11, 6)
    with pytest.raises(ValueError, match="období"):
        compute_period("yearly", UNTIL)
    with pytest.raises(ValueError, match="datum"):
        compute_period("weekly", "2026-13-45")


def test_period_contains_and_labels():
    period = Period("weekly", date(2026, 10, 31), date(2026, 11, 6))
    assert period.contains("2026-10-31") and period.contains("2026-11-06")
    assert period.contains("2026-11-06T23:59:59") and period.contains(date(2026, 11, 1))
    assert not period.contains("2026-10-30") and not period.contains("2026-11-07")
    assert not period.contains(None) and not period.contains("")
    assert period.popis == "31. 10. – 6. 11. 2026"
    assert period.nazev == "Týdenní digest"
    assert Period("monthly", date(2025, 12, 28), date(2026, 1, 3)).popis == "28. 12. 2025 – 3. 1. 2026"
    assert period.as_dict() == {"typ": "weekly", "od": "2026-10-31", "do": "2026-11-06",
                                "nazev": "Týdenní digest", "popis": "31. 10. – 6. 11. 2026"}
    assert format_date_cz("2026-11-06T10:00:00") == "6. 11. 2026"
    assert format_date_cz(None) == "—"
    assert format_date_cz("kdykoli") == "kdykoli"
    assert plural_cz(1, "článek", "články", "článků") == "1 článek"
    assert plural_cz(3, "článek", "články", "článků") == "3 články"
    assert plural_cz(5, "článek", "články", "článků") == "5 článků"


# ── sections ─────────────────────────────────────────────────────


def test_period_boundaries_are_inclusive(weekly):
    cs = _company(weekly, "ceska_sporitelna")
    assert _news_ids(cs) == ["fc-news-2"]                       # 31. 10. in, 30. 10. out
    csob = _company(weekly, "csob")
    assert _news_ids(csob) == ["fc-news-4"]                     # 6. 11. in, 7. 11. out
    mbank = _company(weekly, "mbank")
    assert [k["id"] for k in mbank["kampane"]] == ["fc-campaign-901"]   # 902 updated 1. 10. is out
    assert [p["id"] for p in csob["produkty"]] == ["fc-product-79"]     # 80 updated 1. 10. is out
    assert [m["id"] for m in cs["mystery_shopping"]] == ["fc-ms-5"]     # 7 dated 1. 10. is out
    placeholder = _company(weekly, FINECIM_PLACEHOLDER_COMPETITOR)
    assert [m["id"] for m in placeholder["mystery_shopping"]] == ["fc-ms-6"]  # 31. 10. in


def test_companies_ordered_by_tier_then_name(db, weekly):
    assert [c["id"] for c in weekly["spolecnosti"]] == [
        "ceska_sporitelna", "csob", "mbank", FINECIM_PLACEHOLDER_COMPETITOR,
    ]
    assert [c["tier"] for c in weekly["spolecnosti"]] == [1, 1, 2, None]
    assert weekly["spolecnosti"][-1]["nazev"] == "FINeCIM (nepřiřazeno)"
    assert rank_by_tier({"id": FINECIM_PLACEHOLDER_COMPETITOR, "tier": None, "nazev": "x"})[0] is True
    # the ordering is pluggable (a threat score can replace tier order later)
    reverse = build_digest(db, compute_period("weekly", UNTIL),
                           rank_key=lambda c: (-(c.get("tier") or 0), c["nazev"].casefold()))
    assert [c["id"] for c in reverse["spolecnosti"]] == [
        "mbank", "ceska_sporitelna", "csob", FINECIM_PLACEHOLDER_COMPETITOR,
    ]


def test_headline_numbers(weekly):
    counts = {c["id"]: c["pocty"] for c in weekly["spolecnosti"]}
    assert counts["ceska_sporitelna"] == {"clanky": 1, "kampane": 1, "produkty": 1, "mystery_shopping": 1}
    assert counts["csob"] == {"clanky": 1, "kampane": 0, "produkty": 1, "mystery_shopping": 0}
    assert counts["mbank"] == {"clanky": 1, "kampane": 1, "produkty": 1, "mystery_shopping": 0}
    assert counts[FINECIM_PLACEHOLDER_COMPETITOR] == {"clanky": 0, "kampane": 0, "produkty": 0, "mystery_shopping": 1}
    assert weekly["souhrn"] == {
        "spolecnosti": 4, "clanky": 3, "kampane": 2, "produkty": 3, "mystery_shopping": 2,
        "executive_summary": 2, "trh": 2,
    }
    assert weekly["prazdny"] is False
    assert weekly["period"]["od"] == "2026-10-31" and weekly["filtr_segmentu"] == []
    assert len(weekly["segmenty"]) == 10


def test_product_diff_new_and_updated(weekly):
    george = _company(weekly, "ceska_sporitelna")["produkty"][0]
    assert george["druh"] == "zmena"
    assert george["produktova_linie"] == "Mobilní aplikace"
    assert george["segment"]["slug"] == "ucty" and george["aktualizace"] == "2026-11-04"
    assert george["zmeny"] == [
        {"section": "Aktuální verze", "name": "iOS (verze)", "stara": "26.4.51", "nova": "26.5.0", "druh": "zmena"},
        {"section": "Funkce", "name": "Google Pay", "stara": None, "nova": "ano", "druh": "pridano"},
        {"section": "Funkce", "name": "Apple Pay", "stara": "ano", "nova": None, "druh": "odebrano"},
    ]  # " 7.1 " vs "7.1" is not a change
    assert [a["name"] for a in george["parametry"]] == ["iOS (verze)", "Android (verze)", "Google Pay"]

    novy = _company(weekly, "mbank")["produkty"][0]
    assert novy["id"] == "fc-product-78" and novy["druh"] == "novy" and novy["zmeny"] == []
    assert novy["parametry"] == [{"section": None, "name": "Poplatek", "value": "0 Kč"}]
    assert novy["pridano"] == "2026-11-05" and novy["aktualizace"] == "2026-11-05"

    updated = _company(weekly, "csob")["produkty"][0]
    assert updated["id"] == "fc-product-79" and updated["druh"] == "aktualizace" and updated["zmeny"] == []


def test_diff_atributy_handles_legacy_dict_and_whitespace():
    assert diff_atributy({"a": "1", "b": "2"}, {"a": "1 ", "c": "3"}) == [
        {"section": None, "name": "c", "stara": None, "nova": "3", "druh": "pridano"},
        {"section": None, "name": "b", "stara": "2", "nova": None, "druh": "odebrano"},
    ]
    assert diff_atributy(None, []) == []
    assert diff_atributy([{"name": "x", "value": 1}], [{"name": "x", "value": "1"}]) == []


def test_upsert_produkt_records_a_version_only_when_parameters_change(db):
    versions = db.get_produkt_verze("fc-product-77")
    assert [v["aktualizace"] for v in versions] == ["2026-10-01", "2026-11-04"]
    assert versions[0]["atributy"][0]["value"] == "26.4.51" and versions[0]["zachyceno_at"]
    latest = versions[-1]
    # identical parameters (also with another key order) add no version
    db.upsert_produkt({"id": "fc-product-77", "competitor_id": "ceska_sporitelna", "segment_id": "ucty",
                       "nazev": "George", "aktualizace": "2026-11-05",
                       "atributy": [{"value": a["value"], "name": a["name"], "section": a["section"]}
                                    for a in latest["atributy"]]})
    assert len(db.get_produkt_verze("fc-product-77")) == 2
    # a row without atributy changes nothing; a changed value adds one
    db.upsert_produkt({"id": "fc-product-77", "competitor_id": "ceska_sporitelna", "segment_id": "ucty",
                       "nazev": "George 2"})
    assert len(db.get_produkt_verze("fc-product-77")) == 2
    db.upsert_produkt({"id": "fc-product-77", "competitor_id": "ceska_sporitelna", "segment_id": "ucty",
                       "nazev": "George 2", "atributy": [{"section": None, "name": "iOS (verze)", "value": "27"}]})
    assert len(db.get_produkt_verze("fc-product-77")) == 3
    assert db.get_produkt_verze("fc-product-nope") == []
    assert Database.produkt_atributy_hash([{"a": 1, "b": 2}]) == Database.produkt_atributy_hash([{"b": 2, "a": 1}])


def test_campaigns_started_or_updated_with_first_creative(weekly):
    george = _company(weekly, "ceska_sporitelna")["kampane"][0]
    assert george["druh"] == "nova" and george["zacatek"] == "2026-11-02"
    assert george["url"] == f"{FC}/ucty/campaign/900"
    assert george["media_typy"] == ["TV", "Web"] and george["typy_kampane"] == ["Produktová", "Imageová"]
    assert george["prvni_kreativa"]["id"] == "fc-creative-1"          # the earliest one
    assert george["prvni_kreativa"]["media_druh"] == "video"
    assert george["pocet_kreativ"] == 2
    mkonto = _company(weekly, "mbank")["kampane"][0]
    assert mkonto["druh"] == "aktualizovana" and mkonto["aktualizace"] == "2026-11-05"
    assert mkonto["segment"]["slug"] == "sporeni" and mkonto["url"] == f"{FC}/sporeni/campaign/901"
    assert mkonto["prvni_kreativa"] is None and mkonto["pocet_kreativ"] == 0


def test_mystery_shopping_with_pdf_link(weekly):
    ms5 = _company(weekly, "ceska_sporitelna")["mystery_shopping"][0]
    assert ms5["pdf_url"] == "https://www.finecim.cz/media/pdf/open?itemId=5"
    assert ms5["url"] == f"{FC}/ucty/mystery-shopping/5" and ms5["datum"] == "2026-11-06"
    ms6 = _company(weekly, FINECIM_PLACEHOLDER_COMPETITOR)["mystery_shopping"][0]
    assert ms6["pdf_url"] == "https://www.finecim.cz/media/pdf/open?itemId=6"   # from the attachments


def test_news_grouped_by_primary_type(weekly):
    mbank = _company(weekly, "mbank")
    assert [g["typ"] for g in mbank["zpravy"]] == ["produkty a služby"]
    item = mbank["zpravy"][0]["polozky"][0]
    assert item["typy_zpravy"] == ["produkty a služby", "tiskové zprávy"]
    assert item["tagy"] == ["mBank", "poplatky"] and item["spolecnost"]["id"] == "mbank"
    assert item["segment"]["nazev"] == "Účty"


def test_executive_summaries_overlapping_the_period(db, weekly):
    assert [(s["id"], s["segment"]["slug"]) for s in weekly["executive_summary"]] == [
        ("fc-es-12", "ucty"), ("fc-es-10", "hypoteky"),
    ]
    es = weekly["executive_summary"][0]
    assert es["nazev"] == "listopad 2026" and (es["rok"], es["mesic"]) == (2026, 11)
    assert [(p["nazev"], p["url"], p["typ"]) for p in es["polozky"]] == [
        ("mBank mění ceník", f"{FC}/ucty/news/1", "news"), ("Kampaň", f"{FC}/ucty/campaign/900", "campaign"),
    ]
    later = build_digest(db, compute_period("weekly", "2026-11-13"))      # 7.–13. 11.: October is out
    assert [s["id"] for s in later["executive_summary"]] == ["fc-es-12"]
    monthly = build_digest(db, compute_period("monthly", UNTIL))           # 7. 10.–6. 11.
    assert {s["id"] for s in monthly["executive_summary"]} == {"fc-es-12", "fc-es-10"}


def test_market_news_section(weekly):
    groups = {g["typ"]: [i["id"] for i in g["polozky"]] for g in weekly["trh"]}
    assert groups == {"regulace": ["fc-news-6"], "ostatní": ["fc-news-7"]}
    assert [g["typ"] for g in weekly["trh"]] == ["regulace", "ostatní"]       # "ostatní" last
    trh_item = weekly["trh"][1]["polozky"][0]
    assert trh_item["spolecnost"]["nazev"] == "ČSOB" and trh_item["segment"]["slug"] == "bankovni-trh"
    assert "fc-news-7" not in _news_ids(_company(weekly, "csob"))             # not duplicated


def test_segment_filter(db):
    period = compute_period("weekly", UNTIL)
    digest = build_digest(db, period, ["sporeni"])
    assert [c["id"] for c in digest["spolecnosti"]] == ["mbank"]
    assert digest["souhrn"]["kampane"] == 1 and digest["souhrn"]["clanky"] == 0
    assert digest["filtr_segmentu"] == ["sporeni"]
    assert [s["slug"] for s in digest["segmenty"]] == ["sporeni"]
    assert digest_filename(digest, "md") == "digest-weekly-2026-11-06-sporeni.md"
    both = build_digest(db, period, ["ucty", "hypoteky", "ucty"])
    assert {c["id"] for c in both["spolecnosti"]} == {"ceska_sporitelna", "csob", "mbank",
                                                      FINECIM_PLACEHOLDER_COMPETITOR}
    assert [g["typ"] for g in both["trh"]] == ["regulace"]                     # bankovni-trh filtered out
    assert digest_filename(both, "html") == "digest-weekly-2026-11-06-ucty+hypoteky.html"
    with pytest.raises(ValueError, match="Neznámý segment: nope"):
        build_digest(db, period, ["nope"])


def test_empty_period(db):
    digest = build_digest(db, compute_period("weekly", "2025-01-10"))
    assert digest["prazdny"] is True
    assert digest["spolecnosti"] == [] and digest["executive_summary"] == [] and digest["trh"] == []
    assert set(digest["souhrn"].values()) == {0}
    md = render_markdown(digest)
    assert EMPTY_ALL in md and EMPTY_SUMMARIES in md and EMPTY_MARKET in md
    assert [t for t in SECTION_TITLES if f"## {t}" in md] == list(SECTION_TITLES)
    html = render_html(digest)
    assert EMPTY_ALL in html and html.startswith("<!doctype html>") and '<html lang="cs">' in html
    assert digest_filename(digest, "md") == "digest-weekly-2025-01-10.md"


# ── renderers ────────────────────────────────────────────────────


def test_render_markdown_reads_well(weekly):
    md = render_markdown(weekly)
    lines = md.splitlines()
    assert lines[0] == "# Týdenní digest konkurence: 31. 10. – 6. 11. 2026"
    assert "- Období: 31. 10. 2026 – 6. 11. 2026 (týdenní)" in lines
    headings = [ln for ln in lines if ln.startswith("## ")]
    assert headings == [f"## {t}" for t in SECTION_TITLES]
    # headline table, tier 1 first
    table = [ln for ln in lines if ln.startswith("| ")]
    assert table[0] == "| Společnost | Tier | Články | Kampaně | Produkty | Mystery shopping |"
    assert table[1] == "| Česká spořitelna | 1 | 1 | 1 | 1 | 1 |"
    assert table[2] == "| ČSOB | 1 | 1 | 0 | 1 | 0 |"
    assert table[3] == "| mBank | 2 | 1 | 1 | 1 | 0 |"
    assert table[4] == "| FINeCIM (nepřiřazeno) | — | 0 | 0 | 0 | 1 |"
    assert "Celkem: 4 společnosti · 3 články · 2 kampaně · 3 produkty · 2 mystery shopping · 2 executive summary · 2 zprávy z trhu" in lines
    # company sections in tier order
    sections = [ln for ln in lines if ln.startswith("### ")]
    assert sections[:4] == ["### Česká spořitelna (Tier 1)", "### ČSOB (Tier 1)", "### mBank (Tier 2)",
                            "### FINeCIM (nepřiřazeno)"]
    assert "- **Změna parametrů:** [George](https://www.finecim.cz/cz/domena/ucty/produkt/77) · Účty / Mobilní aplikace · Fyzické osoby · aktualizace 4. 11. 2026" in lines
    assert "  - Aktuální verze: iOS (verze): 26.4.51 → 26.5.0" in lines
    assert "  - Funkce: Google Pay: nově ano" in lines
    assert "  - Funkce: Apple Pay: odebráno (dříve ano)" in lines
    assert "- **Nový produkt:** [mKonto Plus](https://www.finecim.cz/cz/domena/ucty/produkt/78) · Účty" in lines
    assert "  - Poplatek: 0 Kč" in lines
    assert "- **Aktualizace:** [Plus konto](https://www.finecim.cz/cz/domena/ucty/produkt/79) · Účty · aktualizace 2. 11. 2026 · bez zjištěné změny parametrů" in lines
    assert "- **Nová kampaň:** [Kampaň George](https://www.finecim.cz/cz/domena/ucty/campaign/900) (Účty) · začátek 2. 11. 2026 · média: TV, Web · typ: Produktová, Imageová" in lines
    assert "  - První kreativa: 2. 11. 2026 · TV · [Spot](https://www.finecim.cz/media/download/default/10) (celkem 2 kreativy)" in lines
    assert "- **Aktualizovaná kampaň:** [mKonto](https://www.finecim.cz/cz/domena/sporeni/campaign/901) (Spoření) · začátek 1. 9. 2026 · aktualizace 5. 11. 2026 · média: Social" in lines
    assert "- produkty a služby" in lines
    assert "  - 5. 11. 2026 · [mBank mění ceník](https://www.finecim.cz/cz/domena/ucty/news/1) (Účty) — Perex 1" in lines
    assert "  - 31. 10. 2026 · [ČS \\[novinka\\] \\| start](https://www.finecim.cz/cz/domena/ucty/news/2) (Účty) — Perex 2" in lines
    assert "- 6. 11. 2026 · [MS onboarding](https://www.finecim.cz/cz/domena/ucty/mystery-shopping/5) (Účty) · [PDF zpráva](https://www.finecim.cz/media/pdf/open?itemId=5)" in lines
    assert "### Účty · listopad 2026" in lines
    assert "- **mBank mění ceník** — Shrnutí 1 ([odkaz](https://www.finecim.cz/cz/domena/ucty/news/1))" in lines
    assert "  - 4. 11. 2026 · ČSOB na trhu (Bankovní trh · ČSOB)" in lines
    assert "  - 3. 11. 2026 · [ČNB sazby](https://www.finecim.cz/cz/domena/ucty/news/6) (Účty) — Perex 6" in lines
    assert md.endswith("\n") and "\n\n\n" not in md


def test_render_html_structure_and_escaping(db):
    _news(db, 99, "mbank", "ucty", "2026-11-04", "tiskové zprávy",
          nazev='<script>alert("x")</script> & spol.', perex="a < b")
    digest = build_digest(db, compute_period("weekly", UNTIL))
    html = render_html(digest)
    assert "<script>" not in html and "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; spol." in html
    assert "a &lt; b" in html
    assert "<title>Týdenní digest konkurence: 31. 10. – 6. 11. 2026</title>" in html
    for title in SECTION_TITLES:
        assert f"<h2>{title}</h2>" in html
    assert html.index("<h2>1.") < html.index("<h2>2.") < html.index("<h2>3.") < html.index("<h2>4.")
    assert '<h3 id="spolecnost-ceska_sporitelna">Česká spořitelna <span class="tier tier-1">Tier 1</span></h3>' in html
    assert html.index('id="spolecnost-ceska_sporitelna"') < html.index('id="spolecnost-mbank"')
    assert '<span class="old">26.4.51</span> → <strong>26.5.0</strong>' in html
    assert '<a href="https://www.finecim.cz/media/pdf/open?itemId=5" target="_blank" rel="noopener noreferrer">PDF zpráva</a>' in html
    assert '<span class="chip">TV</span>' in html
    assert "Celkem: 4 společnosti" in html


def test_write_digest_files(weekly, tmp_path):
    out = tmp_path / "out" / "nested"
    paths = write_digest(weekly, out, ("both",))
    assert [p.name for p in paths] == ["digest-weekly-2026-11-06.md", "digest-weekly-2026-11-06.html"]
    assert paths[0].read_text(encoding="utf-8") == render_markdown(weekly)
    assert paths[1].read_text(encoding="utf-8") == render_html(weekly)
    assert [p.name for p in write_digest(weekly, out, ("html",))] == ["digest-weekly-2026-11-06.html"]
    assert [p.name for p in write_digest(weekly, out, ("md", "html", "both"))] == [
        "digest-weekly-2026-11-06.md", "digest-weekly-2026-11-06.html",
    ]
    with pytest.raises(ValueError, match="formát"):
        write_digest(weekly, out, ("pdf",))


# ── CLI ──────────────────────────────────────────────────────────


@pytest.fixture
def cli_config(tmp_path, db_path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "settings.yaml").write_text(yaml.safe_dump({"database": {"path": db_path}}), encoding="utf-8")
    return config_dir


def test_cli_digest_writes_both_formats(cli_config, tmp_path):
    out = tmp_path / "digests"
    result = CliRunner().invoke(cli_mod.cli, [
        "--config-dir", str(cli_config), "digest", "--period", "weekly", "--until", UNTIL,
        "--format", "both", "--output", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert "Týdenní digest 31. 10. – 6. 11. 2026" in result.output
    assert "4 společností" in result.output and "3 článků" in result.output
    assert sorted(p.name for p in out.iterdir()) == ["digest-weekly-2026-11-06.html", "digest-weekly-2026-11-06.md"]
    md = (out / "digest-weekly-2026-11-06.md").read_text(encoding="utf-8")
    assert md.startswith("# Týdenní digest konkurence: 31. 10. – 6. 11. 2026")
    assert "### Česká spořitelna (Tier 1)" in md

    result = CliRunner().invoke(cli_mod.cli, [
        "--config-dir", str(cli_config), "digest", "-p", "monthly", "--until", UNTIL, "-s", "sporeni", "-o", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert "Měsíční digest 7. 10. – 6. 11. 2026" in result.output
    assert (out / "digest-monthly-2026-11-06-sporeni.md").exists()


def test_cli_digest_rejects_bad_input(cli_config, tmp_path):
    bad_date = CliRunner().invoke(cli_mod.cli, ["--config-dir", str(cli_config), "digest", "--until", "2026-13-45",
                                                "-o", str(tmp_path)])
    assert bad_date.exit_code == 1 and "Neplatné datum" in bad_date.output
    bad_segment = CliRunner().invoke(cli_mod.cli, ["--config-dir", str(cli_config), "digest", "-s", "nope",
                                                   "-o", str(tmp_path)])
    assert bad_segment.exit_code == 1 and "Neznámý segment: nope" in bad_segment.output
    bad_period = CliRunner().invoke(cli_mod.cli, ["--config-dir", str(cli_config), "digest", "--period", "yearly"])
    assert bad_period.exit_code == 2


# ── API ──────────────────────────────────────────────────────────


@pytest.fixture
def api_client(db_path, monkeypatch):
    monkeypatch.delenv("CI_MONITOR_API_KEY", raising=False)
    app = create_app(db_path)
    app.config["TESTING"] = True
    return app.test_client()


def test_api_digest_json_matches_builder(api_client, db):
    resp = api_client.get(f"/api/digest?period=weekly&until={UNTIL}")
    assert resp.status_code == 200
    data = resp.get_json()
    expected = build_digest(db, compute_period("weekly", UNTIL))
    for key in ("period", "souhrn", "spolecnosti", "executive_summary", "trh", "segmenty", "filtr_segmentu", "prazdny"):
        assert data[key] == expected[key], key
    assert data["period"]["popis"] == "31. 10. – 6. 11. 2026"
    assert [c["id"] for c in data["spolecnosti"]][:2] == ["ceska_sporitelna", "csob"]
    # default period is weekly ending today; segments are repeatable
    assert api_client.get("/api/digest").get_json()["period"]["do"] == date.today().isoformat()
    filtered = api_client.get(f"/api/digest?until={UNTIL}&segment=ucty&segment=hypoteky").get_json()
    assert filtered["filtr_segmentu"] == ["ucty", "hypoteky"]


def test_api_digest_text_formats_and_errors(api_client, db):
    md = api_client.get(f"/api/digest?period=weekly&until={UNTIL}&format=md")
    assert md.status_code == 200 and md.mimetype == "text/markdown"

    def without_timestamp(text: str) -> str:
        return "\n".join(ln for ln in text.splitlines() if not ln.startswith("- Vygenerováno"))

    expected = render_markdown(build_digest(db, compute_period("weekly", UNTIL)))
    assert without_timestamp(md.get_data(as_text=True)) == without_timestamp(expected)
    html = api_client.get(f"/api/digest?period=monthly&until={UNTIL}&format=html")
    assert html.status_code == 200 and html.mimetype == "text/html"
    assert "<title>Měsíční digest konkurence: 7. 10. – 6. 11. 2026</title>" in html.get_data(as_text=True)
    for query in ("period=yearly", "until=2026-99-01&period=weekly", "format=pdf", f"until={UNTIL}&segment=nope"):
        resp = api_client.get(f"/api/digest?{query}")
        assert resp.status_code == 400, query
    assert "Neznámý segment: nope" in api_client.get(f"/api/digest?until={UNTIL}&segment=nope").get_data(as_text=True)
    status = api_client.get("/api/finecim/status").get_json()
    assert status["pocty"]["produkty_verze"] == 5    # 77 twice, 78, 79, 80 once each
