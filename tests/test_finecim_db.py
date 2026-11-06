"""Database layer for the FINeCIM scraper: schema additions, upserts and sync helpers."""

import json
from pathlib import Path

import pytest
import yaml
from src.models.database import FINECIM_PLACEHOLDER_COMPETITOR, Database, load_subject_competitor_map

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture
def db(tmp_path) -> Database:
    database = Database(str(tmp_path / "finecim.sqlite"))
    database.initialize()
    database.seed_segments(str(CONFIG_DIR))
    database.seed_competitors(str(CONFIG_DIR))
    yield database
    database.close()


def _count(db: Database, table: str, where: str = "1=1", params: tuple = ()) -> int:
    return db.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]


# ── seeding / config ─────────────────────────────────────────────


def test_seeding_yields_ten_segments_with_product_lines(db):
    segmenty = {s["id"]: s for s in db.get_segmenty()}
    assert set(segmenty) == {
        "ucty", "sporeni", "uvery", "hypoteky", "investice", "bankovni-trh", "fintech",
        "bankopojisteni", "stavebni-sporitelny", "penzijni-spolecnosti",
    }
    assert segmenty["bankovni-trh"]["ma_produkty"] == 0
    assert segmenty["fintech"]["ma_produkty"] == 0
    assert segmenty["penzijni-spolecnosti"]["ma_produkty"] == 1
    for seg in segmenty.values():
        assert seg["finecim_slug"] == seg["slug"]

    def lines(seg_id):
        return {r["slug"]: r for r in db.get_produktove_linie(seg_id)}

    # existing ids/slugs are kept and gain finecim ids
    ucty = lines("ucty")
    assert {k: v["finecim_id"] for k, v in ucty.items()} == {
        "bezne_ucty": 1, "debetni_karty": 2, "mobilni_aplikace": 53,
    }
    assert ucty["bezne_ucty"]["id"] == "ucty__bezne_ucty"
    assert set(lines("hypoteky")) == {"hypoteky", "americke_hypoteky", "pojisteni_schopnosti_splacet"}
    assert set(lines("investice")) == {"investicni_fondy", "investicni_platformy", "penzijni_sporeni"}
    # new domains carry every FINeCIM product line
    assert set(lines("uvery")) == {
        "konsolidace", "kontokorenty", "kreditni_karty", "mikropujcky", "nakup_na_splatky", "uvery",
    }
    assert {r["finecim_id"] for r in lines("bankopojisteni").values()} == {56, 57, 58, 60, 61}
    assert lines("penzijni-spolecnosti")["penzijni_sporeni"]["finecim_id"] == 48
    assert len(lines("stavebni-sporitelny")) == 3


def test_segments_match_finecim_taxonomy():
    finecim = yaml.safe_load((CONFIG_DIR / "finecim.yaml").read_text(encoding="utf-8"))
    segments = yaml.safe_load((CONFIG_DIR / "segments.yaml").read_text(encoding="utf-8"))["segmenty"]
    by_slug = {s["finecim_slug"]: s for s in segments}
    assert set(by_slug) == set(finecim["segments"])
    for slug, fc in finecim["segments"].items():
        configured = {pl["finecim_id"]: pl["nazev"] for pl in by_slug[slug]["produktove_linie"]
                      if "finecim_id" in pl}
        assert configured == {int(k): v for k, v in fc["product_lines"].items()}, slug
        for pl in by_slug[slug]["produktove_linie"]:
            assert pl["slug"].isascii() and "-" not in pl["slug"]


def test_init_is_idempotent(db):
    before = (_count(db, "segmenty"), _count(db, "produktove_linie"), _count(db, "competitors"))
    db.initialize()
    db.seed_segments(str(CONFIG_DIR))
    db.seed_competitors(str(CONFIG_DIR))
    after = (_count(db, "segmenty"), _count(db, "produktove_linie"), _count(db, "competitors"))
    assert before == after
    assert before[0] == 10


def test_seed_resolves_existing_line_by_finecim_id_or_name(tmp_path):
    database = Database(str(tmp_path / "x.sqlite"))
    database.initialize()
    cfg = tmp_path / "cfg"
    cfg.mkdir()

    def seed(lines):
        (cfg / "segments.yaml").write_text(
            yaml.safe_dump({"segmenty": [{"id": "ucty", "slug": "ucty", "nazev": "Účty",
                                          "produktove_linie": lines}]}, allow_unicode=True),
            encoding="utf-8",
        )
        database.seed_segments(str(cfg))

    seed([{"slug": "bezne", "nazev": "Běžné účty", "finecim_id": 1},
          {"slug": "karty", "nazev": "Debetní karty"}])
    # renamed slugs: matched by finecim_id and by name, no duplicates
    seed([{"slug": "bezne_ucty", "nazev": "Běžné účty (nové)", "finecim_id": 1},
          {"slug": "debetni_karty", "nazev": "Debetní karty", "finecim_id": 2}])
    rows = {r["id"]: r for r in database.get_produktove_linie("ucty")}
    assert set(rows) == {"ucty__bezne", "ucty__karty"}
    assert rows["ucty__bezne"]["nazev"] == "Běžné účty (nové)"
    assert rows["ucty__karty"]["finecim_id"] == 2
    assert database.resolve_produktova_linie("ucty", finecim_id=2) == "ucty__karty"
    assert database.resolve_produktova_linie("ucty", nazev=" debetní KARTY ") == "ucty__karty"
    assert database.resolve_produktova_linie("ucty", nazev="neexistuje") is None
    database.close()


# ── subjects / competitors ───────────────────────────────────────


def test_subject_competitor_map_reads_config():
    mapping = load_subject_competitor_map(CONFIG_DIR)
    assert mapping[11] == "ceska_sporitelna"
    assert len(mapping) == 19
    assert load_subject_competitor_map() == mapping
    assert load_subject_competitor_map(CONFIG_DIR / "does-not-exist") == {}


def test_ensure_competitor_mapped_subject(db):
    n = _count(db, "competitors")
    assert db.ensure_competitor_for_subject(11, "Česká spořitelna") == "ceska_sporitelna"
    assert _count(db, "competitors") == n
    assert db.get_competitor("ceska_sporitelna")["tier"] == 1


def test_ensure_competitor_unmapped_subject_created_once(db):
    n = _count(db, "competitors")
    assert db.ensure_competitor_for_subject(999, "Nová banka") == "fc_999"
    assert db.ensure_competitor_for_subject(999, "Nová banka") == "fc_999"
    assert _count(db, "competitors") == n + 1
    comp = db.get_competitor("fc_999")
    assert comp["tier"] == 3
    assert comp["name"] == "Nová banka"
    # empty names get a fallback
    assert db.ensure_competitor_for_subject(56, "") == "fc_56"
    assert db.get_competitor("fc_56")["name"]


def test_ensure_competitor_placeholder(db):
    assert db.ensure_competitor_for_subject(0, "FINeCIM (nepřiřazeno)") == FINECIM_PLACEHOLDER_COMPETITOR
    assert db.get_competitor("__finecim__")["name"] == "FINeCIM (nepřiřazeno)"


def test_ensure_competitor_uses_custom_config_dir(db, tmp_path):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "finecim.yaml").write_text("subject_to_competitor:\n  999: csob\n", encoding="utf-8")
    db.finecim_config_dir = cfg
    assert db.ensure_competitor_for_subject(999, "x") == "csob"
    assert db.ensure_competitor_for_subject(11, "Česká spořitelna") == "fc_11"


def test_upsert_finecim_subject(db):
    db.upsert_finecim_subject(11, "Česká spořitelna", "ceska_sporitelna",
                              "https://www.finecim.cz/cz/domena/ucty/subjekt/11", ["ucty", "nope"])
    db.upsert_finecim_subject(11, "Česká spořitelna a.s.", None, None, ["hypoteky"],
                              aktualizace="2026-11-01")
    subj = db.get_finecim_subject(11)
    assert subj["nazev"] == "Česká spořitelna a.s."
    assert subj["competitor_id"] == "ceska_sporitelna"
    assert subj["url"].endswith("/subjekt/11")
    assert subj["aktualizace"] == "2026-11-01"
    assert subj["segment_ids"] == ["hypoteky", "ucty"]
    assert _count(db, "finecim_subjekty") == 1
    assert db.get_finecim_subject(12345) is None
    # unmapped subject row gets its competitor filled in
    db.upsert_finecim_subject(999, "Nová banka", None, None, ["ucty"])
    db.ensure_competitor_for_subject(999, "Nová banka")
    assert db.get_finecim_subject(999)["competitor_id"] == "fc_999"


# ── entity upserts ───────────────────────────────────────────────


def _clanek(**over):
    row = {
        "id": "fc-news-43573", "competitor_id": "ceska_sporitelna", "segment_id": "ucty",
        "produktova_linie_id": None, "nazev": "Spořitelna mění ceník", "datum": "2026-11-05",
        "typ_zpravy": "produkty a služby, tiskové zprávy", "stav": "new", "perex": "Perex",
        "telo": "<p>Tělo</p>", "tagy": ["ceník", "účty"], "zdrojovy_signal_id": None,
        "url": "https://www.finecim.cz/cz/domena/ucty/news/43573",
    }
    row.update(over)
    return row


def test_upsert_clanek(db):
    assert db.upsert_clanek(_clanek()) is True
    first = db.get_clanek("fc-news-43573")
    assert json.loads(first["tagy"]) == ["ceník", "účty"]
    assert first["pridano_at"]
    assert db.upsert_clanek(_clanek(stav="updated", nazev="Nový titulek",
                                    pridano_at="2000-01-01T00:00:00")) is False
    row = db.get_clanek("fc-news-43573")
    assert row["stav"] == "updated"
    assert row["nazev"] == "Nový titulek"
    assert row["pridano_at"] == first["pridano_at"]
    assert _count(db, "clanky") == 1


def test_upsert_requires_id(db):
    with pytest.raises(ValueError):
        db.upsert_clanek({"nazev": "x", "datum": "2026-01-01"})


def _kampan(**over):
    row = {
        "id": "fc-campaign-901", "competitor_id": "csob", "segment_id": "ucty",
        "nazev": "Kampaň", "zacatek": "2026-09-01", "aktualizace": "2026-10-01",
        "popis": "Popis", "media_typy": ["TV", "Web"], "typ_kampane": "Produktová",
        "kreativa_url": "https://www.finecim.cz/media/image/default/1",
    }
    row.update(over)
    return row


def test_upsert_kampan_and_kreativy(db):
    assert db.upsert_kampan(_kampan()) is True
    assert db.upsert_kampan(_kampan(aktualizace="2026-11-02")) is False
    rows = db.get_kampane(media_typ="TV")
    assert len(rows) == 1 and rows[0]["aktualizace"] == "2026-11-02"

    kreativy = [
        {"id": "fc-creative-1", "datum": "2026-09-01", "media_typ": "TV", "popis": "spot",
         "media_url": "https://www.finecim.cz/media/download/default/1", "media_druh": "video"},
        {"id": "fc-creative-2", "datum": "2026-09-02", "media_typ": "Web", "popis": "banner",
         "media_url": "https://www.finecim.cz/media/image/default/2", "media_druh": "image"},
    ]
    assert db.replace_kampan_kreativy("fc-campaign-901", kreativy) == 2
    assert db.replace_kampan_kreativy("fc-campaign-901", kreativy[:1]) == 1
    stored = db.conn.execute("SELECT * FROM kampane_kreativy").fetchall()
    assert [r["id"] for r in stored] == ["fc-creative-1"]
    assert stored[0]["kampan_id"] == "fc-campaign-901"


def test_upsert_mystery(db):
    row = {"id": "fc-ms-77", "competitor_id": None, "segment_id": "ucty", "nazev": "MS účet",
           "datum": "2026-10-10", "popis": "a", "pdf_url": None}
    assert db.upsert_mystery(row) is True
    assert db.upsert_mystery({**row, "pdf_url": "https://www.finecim.cz/media/pdf/open?itemId=5"}) is False
    rows = db.get_mystery_shopping(segment_id="ucty")
    assert len(rows) == 1 and rows[0]["pdf_url"].endswith("itemId=5")


def test_upsert_produkt(db):
    row = {"id": "fc-product-310", "competitor_id": "moneta", "segment_id": "ucty",
           "produktova_linie_id": db.resolve_produktova_linie("ucty", nazev="Mobilní aplikace"),
           "zakaznicky_segment": "Fyzické osoby", "nazev": "Smart Banka",
           "kratky_popis": "Aplikace", "atributy": [{"section": "Aktuální verze",
                                                     "name": "iOS (verze)", "value": "26.4.51"}],
           "url": "https://www.finecim.cz/cz/domena/ucty/produkt/310", "aktivni": 1}
    assert db.upsert_produkt(row) is True
    assert db.upsert_produkt({**row, "kratky_popis": "Nová verze", "aktualizace": "2026-11-04"}) is False
    rows = db.get_produkty(produktova_linie_id="ucty__mobilni_aplikace")
    assert len(rows) == 1
    assert rows[0]["kratky_popis"] == "Nová verze"
    assert json.loads(rows[0]["atributy"])[0]["value"] == "26.4.51"


def test_upsert_executive_summary(db):
    row = {"id": "fc-es-120", "segment_id": "ucty", "rok": 2026, "mesic": 6,
           "nazev": "červen 2026", "telo": "- [A](u): t", "pdf_url": None}
    polozky = [
        {"id": "fc-es-entry-1", "clanek_id": "fc-news-1", "nazev": "A", "text": "t", "poradi": 0},
        {"entry_id": 2, "clanek_id": "fc-news-2", "nazev": "B", "text": "u"},
    ]
    assert db.upsert_executive_summary(row, polozky) is True
    assert db.upsert_executive_summary({**row, "telo": "nové"}, polozky[:1]) is False
    summaries = db.get_executive_summary("ucty")
    assert len(summaries) == 1 and summaries[0]["telo"] == "nové"
    entries = db.conn.execute("SELECT * FROM executive_summary_polozky").fetchall()
    assert [e["id"] for e in entries] == ["fc-es-entry-1"]

    # a summary for the same month stored under another id is re-keyed, not duplicated
    db.conn.execute(
        """INSERT INTO executive_summary (id, segment_id, rok, mesic, nazev, pridano_at)
           VALUES ('legacy', 'ucty', 2026, 5, 'květen', '2026-06-01')""")
    db.conn.commit()
    assert db.upsert_executive_summary({**row, "id": "fc-es-119", "mesic": 5}, polozky) is False
    ids = {s["id"] for s in db.get_executive_summary("ucty")}
    assert ids == {"fc-es-120", "fc-es-119"}
    entry_2 = db.conn.execute(
        "SELECT * FROM executive_summary_polozky WHERE id = 'fc-es-entry-2'").fetchone()
    assert entry_2["summary_id"] == "fc-es-119" and entry_2["poradi"] == 1


def test_executive_summary_entries_store_url_and_typ(db):
    row = {"id": "fc-es-130", "segment_id": "ucty", "rok": 2026, "mesic": 7, "nazev": "červenec"}
    polozky = [
        {"entry_id": 1, "clanek_id": "fc-news-1", "nazev": "Zpráva", "text": "a",
         "url": "https://www.finecim.cz/cz/domena/ucty/news/1", "typ": "news"},
        {"entry_id": 2, "clanek_id": None, "nazev": "Kampaň", "text": "b",
         "url": "https://www.finecim.cz/cz/domena/ucty/campaign/4695", "typ": "campaign"},
        {"entry_id": 3, "nazev": "Bez odkazu", "text": "c"},
    ]
    db.upsert_executive_summary(row, polozky)
    rows = {r["id"]: dict(r) for r in db.conn.execute("SELECT * FROM executive_summary_polozky")}
    assert rows["fc-es-entry-1"]["typ"] == "news"
    assert rows["fc-es-entry-1"]["url"].endswith("/news/1")
    assert rows["fc-es-entry-2"]["typ"] == "campaign"
    assert rows["fc-es-entry-2"]["url"].endswith("/campaign/4695")
    assert rows["fc-es-entry-2"]["clanek_id"] is None
    assert rows["fc-es-entry-3"]["url"] is None and rows["fc-es-entry-3"]["typ"] is None


def test_init_adds_url_and_typ_to_an_existing_polozky_table(tmp_path):
    import sqlite3

    path = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE executive_summary_polozky (
               id TEXT PRIMARY KEY, summary_id TEXT NOT NULL, clanek_id TEXT,
               nazev TEXT, text TEXT, poradi INTEGER)""")
    conn.execute("INSERT INTO executive_summary_polozky (id, summary_id) VALUES ('old', 'fc-es-1')")
    conn.commit()
    conn.close()

    database = Database(str(path))
    try:
        database.initialize()
        columns = database._table_columns("executive_summary_polozky")
        assert "url" in columns and "typ" in columns
        old = database.conn.execute("SELECT * FROM executive_summary_polozky WHERE id = 'old'").fetchone()
        assert old["url"] is None and old["typ"] is None
        database.initialize()  # idempotent
        assert database._table_columns("executive_summary_polozky").count("url") == 1
    finally:
        database.close()


def test_executive_summary_update_keeps_the_first_segment(db):
    row = {"id": "fc-es-140", "segment_id": "ucty", "rok": 2026, "mesic": 8, "nazev": "srpen"}
    assert db.upsert_executive_summary(row, []) is True
    # the same month page reached through another domain
    assert db.upsert_executive_summary(
        {**row, "segment_id": "sporeni", "telo": "nové"}, [{"entry_id": 9, "nazev": "X"}]
    ) is False
    stored = db.conn.execute("SELECT * FROM executive_summary WHERE id = 'fc-es-140'").fetchone()
    assert stored["segment_id"] == "ucty"
    assert stored["telo"] == "nové"
    assert [s["id"] for s in db.get_executive_summary("ucty")] == ["fc-es-140"]
    assert db.get_executive_summary("sporeni") == []
    entries = db.conn.execute(
        "SELECT summary_id FROM executive_summary_polozky WHERE id = 'fc-es-entry-9'").fetchone()
    assert entries["summary_id"] == "fc-es-140"


def test_upsert_spolecnost_detail(db):
    db.ensure_competitor_for_subject(999, "Nová banka")
    db.upsert_spolecnost_detail("fc_999", {
        "popis": "Banka", "sidlo": "Praha", "pocet_klientu": 100,
        "socialni_site": {"web": "https://example.invalid"}, "predstavenstvo": [{"name": "A", "role": "CEO"}],
        "posledni_aktualizace": "2026-10-01", "ico": "45244782",
    })
    db.upsert_spolecnost_detail("fc_999", {"pocet_klientu": 200, "ico": "11111111"})
    detail = db.get_company_detail("fc_999")
    assert detail["pocet_klientu"] == 200
    assert detail["sidlo"] == "Praha"
    assert json.loads(detail["predstavenstvo"])[0]["role"] == "CEO"
    assert detail["ico"] == "45244782"  # filled once, never overwritten
    assert _count(db, "spolecnost_detail") == 1
    # a configured ico is not overwritten
    db.upsert_spolecnost_detail("ceska_sporitelna", {"popis": "x", "ico": "00000000"})
    assert db.get_competitor("ceska_sporitelna")["ico"] == "45244782"


def test_replace_prilohy(db):
    rows = [{"nazev": "VZ 2024", "url": "https://www.finecim.cz/media/pdf/open?itemId=1"},
            {"name": "VZ 2023", "url": "https://www.finecim.cz/media/pdf/open?itemId=2"},
            {"name": "dup", "url": "https://www.finecim.cz/media/pdf/open?itemId=2"},
            {"name": "no url", "url": None}]
    assert db.replace_prilohy("spolecnost", "ceska_sporitelna", rows) == 2
    assert db.replace_prilohy("spolecnost", "ceska_sporitelna", rows[:1]) == 1
    assert db.replace_prilohy("mystery", "fc-ms-77", rows[1:2]) == 1
    assert _count(db, "finecim_prilohy", "entity_type = 'spolecnost'") == 1
    assert _count(db, "finecim_prilohy") == 2


def test_replace_vazby(db):
    assert db.replace_vazby("clanek", "fc-news-1", [11, 2, 11]) == 2
    assert db.replace_vazby("clanek", "fc-news-1", [8]) == 1
    assert db.replace_vazby("clanek", "fc-news-1", []) == 0
    db.replace_vazby("kampan", "fc-campaign-1", [11])
    assert _count(db, "finecim_vazby", "entity_id = 'fc-news-1'") == 0
    assert _count(db, "finecim_vazby") == 1


# ── incremental sync helpers ─────────────────────────────────────


def test_known_finecim_ids(db):
    db.upsert_clanek(_clanek())
    db.upsert_kampan(_kampan())
    db.upsert_kampan(_kampan(id="fc-campaign-902", aktualizace=None))
    db.upsert_mystery({"id": "fc-ms-77", "segment_id": "ucty", "nazev": "MS", "datum": "2026-10-10"})
    db.upsert_produkt({"id": "fc-product-310", "competitor_id": "moneta", "segment_id": "ucty",
                       "nazev": "P", "pridano_at": "2026-09-09T10:00:00"})
    db.upsert_produkt({"id": "fc-product-311", "competitor_id": "moneta", "segment_id": "ucty",
                       "nazev": "Q", "aktualizace": "2026-11-01"})
    db.upsert_executive_summary({"id": "fc-es-120", "segment_id": "ucty", "rok": 2026, "mesic": 6,
                                 "pridano_at": "2026-07-01T08:00:00"}, [])
    db.upsert_finecim_subject(11, "ČS", "ceska_sporitelna", None, [], aktualizace="2026-08-01")

    assert db.known_finecim_ids("news", [43573, 1, 43573]) == {43573: "2026-11-05"}
    assert db.known_finecim_ids("campaign", [901, 902, 903]) == {901: "2026-10-01", 902: None}
    assert db.known_finecim_ids("mystery", [77]) == {77: "2026-10-10"}
    assert db.known_finecim_ids("product", [310, 311]) == {310: "2026-09-09", 311: "2026-11-01"}
    assert db.known_finecim_ids("summary", [120, 121]) == {120: "2026-07-01"}
    assert db.known_finecim_ids("company", [11, 12]) == {11: "2026-08-01"}
    assert db.known_finecim_ids("clanek", [43573]) == {43573: "2026-11-05"}
    assert db.known_finecim_ids("news", []) == {}
    assert len(db.known_finecim_ids("news", list(range(1200)) + [43573])) == 1
    with pytest.raises(ValueError):
        db.known_finecim_ids("bogus", [1])


def test_finecim_sync_round_trip(db):
    assert db.get_finecim_sync("news", "ucty") is None
    db.set_finecim_sync("news", "ucty", last_run_at="2026-11-05T10:00:00", last_page=3,
                        newest_id=43573)
    db.set_finecim_sync("news", "ucty", last_success_at="2026-11-05T10:05:00", note="ok")
    state = db.get_finecim_sync("news", "ucty")
    assert state == {
        "entity": "news", "segment_id": "ucty", "last_run_at": "2026-11-05T10:00:00",
        "last_success_at": "2026-11-05T10:05:00", "last_page": 3, "newest_id": 43573, "note": "ok",
    }
    db.set_finecim_sync("company", "*")
    assert db.get_finecim_sync("company", "*")["last_run_at"] is None
    with pytest.raises(ValueError):
        db.set_finecim_sync("news", "ucty", bogus=1)
