import pytest
import yaml
from src.api import create_app, sanitize_html
from src.models import Signal
from src.models.database import Database


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


# ── FINeCIM content (rows shaped per SCRAPER-DESIGN.md section 4) ──

FC = "https://www.finecim.cz/cz/domena/ucty"


@pytest.fixture
def finecim_client(seeded_db, tmp_config_dir, monkeypatch):
    monkeypatch.delenv("CI_MONITOR_API_KEY", raising=False)
    db = seeded_db
    (tmp_config_dir / "segments.yaml").write_text(
        yaml.safe_dump({"segmenty": [{
            "id": "ucty", "slug": "ucty", "finecim_slug": "ucty", "nazev": "Účty", "poradi": 1,
            "produktove_linie": [
                {"slug": "mobilni_aplikace", "nazev": "Mobilní aplikace", "finecim_id": 53},
            ],
        }]}, allow_unicode=True),
        encoding="utf-8",
    )
    db.seed_segments(str(tmp_config_dir))

    # Subjects: 52 -> mbank, 11 -> ceska_sporitelna (mapping from config/finecim.yaml)
    mbank = db.ensure_competitor_for_subject(52, "mBank")
    cs = db.ensure_competitor_for_subject(11, "Česká spořitelna")
    assert (mbank, cs) == ("mbank", "ceska_sporitelna")
    db.upsert_finecim_subject(52, "mBank", mbank, f"{FC}/subjekt/52", ["ucty"],
                              logo_url="https://www.finecim.cz/media/image/default/52")
    db.upsert_finecim_subject(11, "Česká spořitelna", cs, f"{FC}/subjekt/11", ["ucty"],
                              logo_url="https://www.finecim.cz/media/image/default/11")

    # News: an older one and a newer one (related subject 52) with sanitised HTML bodies
    db.upsert_clanek({
        "id": "fc-news-43000", "competitor_id": cs, "segment_id": "ucty",
        "nazev": "Starší zpráva", "datum": "2026-10-01", "typ_zpravy": "tiskové zprávy",
        "stav": "new", "perex": "Starší", "telo": "<p>Starší</p>", "tagy": ["Účty"],
        "url": f"{FC}/news/43000",
    })
    db.upsert_clanek({
        "id": "fc-news-43573", "competitor_id": mbank, "segment_id": "ucty",
        "produktova_linie_id": None, "nazev": "mBank mění ceník", "datum": "2026-11-05",
        "typ_zpravy": "produkty a služby, tiskové zprávy", "stav": "updated",
        "perex": "Perex zprávy.",
        "telo": '<p>Text <a href="https://www.mbank.cz/">odkaz</a></p>'
                '<script>alert(1)</script><p><a href="javascript:alert(1)">x</a></p>',
        "tagy": ["mBank", "poplatky"], "zdrojovy_signal_id": None,
        "url": f"{FC}/news/43573",
    })
    db.replace_vazby("clanek", "fc-news-43573", [52])

    # Campaign with two creatives
    db.upsert_kampan({
        "id": "fc-campaign-900", "competitor_id": cs, "segment_id": "ucty",
        "nazev": "Kampaň George", "zacatek": "2026-09-01", "aktualizace": "2026-10-15",
        "popis": "Anotace kampaně", "media_typy": ["TV", "Web"],
        "typ_kampane": "Produktová, Imageová",
        "kreativa_url": "https://www.finecim.cz/media/image/default/1",
    })
    db.replace_kampan_kreativy("fc-campaign-900", [
        {"id": "fc-creative-1", "datum": "2026-09-01", "media_typ": "TV", "popis": "Spot",
         "media_url": "https://www.finecim.cz/media/download/default/10", "media_druh": "video"},
        {"id": "fc-creative-2", "datum": "2026-10-15", "media_typ": "Web", "popis": "Banner",
         "media_url": "https://www.finecim.cz/media/image/default/11", "media_druh": "image"},
    ])
    db.replace_vazby("kampan", "fc-campaign-900", [11])

    # Product with parameters
    db.upsert_produkt({
        "id": "fc-product-77", "competitor_id": cs, "segment_id": "ucty",
        "produktova_linie_id": "ucty__mobilni_aplikace", "zakaznicky_segment": "Retail",
        "nazev": "George", "kratky_popis": "Mobilní bankovnictví",
        "atributy": [
            {"section": "Aktuální verze", "name": "iOS (verze)", "value": "26.4.51"},
            {"section": "Aktuální verze", "name": "Android (verze)", "value": "7.1"},
        ],
        "url": f"{FC}/produkt/77", "aktivni": 1,
    })

    # Mystery shopping with a PDF
    db.upsert_mystery({
        "id": "fc-ms-5", "competitor_id": cs, "segment_id": "ucty", "nazev": "MS onboarding",
        "datum": "2026-08-20", "popis": "Perex\n\nText",
        "pdf_url": "https://www.finecim.cz/media/pdf/open?itemId=5",
    })
    db.replace_prilohy("mystery", "fc-ms-5", [
        {"name": "Zpráva", "url": "https://www.finecim.cz/media/pdf/open?itemId=5"},
    ])

    # Executive summary with two entries
    db.upsert_executive_summary(
        {"id": "fc-es-12", "segment_id": "ucty", "rok": 2026, "mesic": 6,
         "nazev": "červen 2026",
         "telo": f"- [mBank mění ceník]({FC}/news/43573): Shrnutí 1\n- [Jiná]({FC}/news/1): Shrnutí 2",
         "pdf_url": None},
        [
            {"entry_id": 101, "clanek_id": "fc-news-43573", "nazev": "mBank mění ceník",
             "text": "Shrnutí 1"},
            {"entry_id": 102, "clanek_id": "fc-news-1", "nazev": "Jiná", "text": "Shrnutí 2"},
        ],
    )

    # Company profile with two annual reports
    db.upsert_spolecnost_detail(cs, {
        "popis": "Největší banka", "zakladni_kapital": "15 200 000 000 Kč",
        "sidlo": "Olbrachtova 1929/62, Praha 4", "akcionar": "Erste Group Bank AG",
        "pocet_klientu": 4600000, "pocet_pobocek": 346, "pocet_bankomatu": 1625,
        "socialni_site": {"facebook": "https://www.facebook.com/ceskasporitelna",
                          "web": "https://www.csas.cz"},
        "predstavenstvo": [{"name": "Tomáš Salomon", "role": "předseda"}],
        "posledni_aktualizace": "2026-10-30", "ico": "45244782",
    })
    db.replace_prilohy("spolecnost", cs, [
        {"name": "Ceska-sporitelna-vyrocni-zprava-2024",
         "url": "https://www.finecim.cz/media/pdf/open?itemId=901"},
        {"name": "Ceska-sporitelna-vyrocni-zprava-2023",
         "url": "https://www.finecim.cz/media/pdf/open?itemId=902"},
    ])
    db.set_finecim_sync("news", "ucty", last_run_at="2026-11-05T08:00:00",
                        last_success_at="2026-11-05T08:01:00", last_page=1, newest_id=43573)

    db_path = db.db_path
    db.close()
    app = create_app(db_path)
    app.config["TESTING"] = True
    return app.test_client()


def test_segmenty_include_finecim_companies_and_counts(finecim_client):
    data = finecim_client.get("/api/segmenty").get_json()
    ucty = next(s for s in data if s["slug"] == "ucty")
    ids = {c["id"] for c in ucty["spolecnosti"]}
    assert {"mbank", "ceska_sporitelna"} <= ids
    assert ucty["pocty"]["clanky"] == 2
    assert ucty["pocty"]["kampane"] == 1
    assert ucty["produktove_linie"][0]["id"] == "ucty__mobilni_aplikace"
    seg = finecim_client.get("/api/segment/ucty").get_json()
    assert {c["id"] for c in seg["spolecnosti"]} == ids


def test_novinky_sorted_with_company_and_tags(finecim_client):
    resp = finecim_client.get("/api/segment/ucty/novinky")
    assert resp.status_code == 200
    clanky = resp.get_json()["clanky"]
    assert [c["id"] for c in clanky] == ["fc-news-43573", "fc-news-43000"]
    first = clanky[0]
    assert first["tagy"] == ["mBank", "poplatky"]
    assert first["typ_zpravy"] == "produkty a služby, tiskové zprávy"
    assert first["typy_zpravy"] == ["produkty a služby", "tiskové zprávy"]
    assert first["spolecnost_nazev"] == "mBank"
    assert first["spolecnost"]["id"] == "mbank"
    assert first["logo_url"] == "https://www.finecim.cz/media/image/default/52"


def test_novinky_filter_by_single_news_type_and_tag(finecim_client):
    one = finecim_client.get("/api/segment/ucty/novinky?typ_zpravy=produkty a služby").get_json()
    assert [c["id"] for c in one["clanky"]] == ["fc-news-43573"]
    both = finecim_client.get("/api/segment/ucty/novinky?typ_zpravy=tiskové zprávy").get_json()
    assert len(both["clanky"]) == 2
    tagged = finecim_client.get("/api/segment/ucty/novinky?tag=poplatky").get_json()
    assert [c["id"] for c in tagged["clanky"]] == ["fc-news-43573"]


def test_clanek_detail_has_body_tags_subjects_and_url(finecim_client):
    resp = finecim_client.get("/api/clanek/fc-news-43573")
    assert resp.status_code == 200
    c = resp.get_json()
    assert c["telo_format"] == "html"
    assert 'href="https://www.mbank.cz/"' in c["telo"] and "odkaz" in c["telo"]
    assert "<script" not in c["telo"] and "javascript:" not in c["telo"]
    assert c["tagy"] == ["mBank", "poplatky"]
    assert c["finecim_url"] == f"{FC}/news/43573"
    subj = c["souvisejici_spolecnosti"]
    assert len(subj) == 1
    assert subj[0]["subject_id"] == 52
    assert subj[0]["competitor_id"] == "mbank"
    assert subj[0]["competitor_name"] == "mBank"
    assert [r["id"] for r in c["related"]] == ["fc-news-43000"]
    assert c["related"][0]["tagy"] == ["Účty"]
    assert finecim_client.get("/api/clanek/fc-news-0").status_code == 404


def test_kampane_include_creatives_newest_first(finecim_client):
    kampane = finecim_client.get("/api/segment/ucty/kampane").get_json()
    assert len(kampane) == 1
    k = kampane[0]
    assert k["media_typy"] == ["TV", "Web"]
    assert k["typy_kampane"] == ["Produktová", "Imageová"]
    assert [kr["id"] for kr in k["kreativy"]] == ["fc-creative-2", "fc-creative-1"]
    assert k["kreativy"][1]["media_druh"] == "video"
    assert k["spolecnost_nazev"] == "Česká spořitelna"
    assert len(finecim_client.get("/api/segment/ucty/kampane?media_typ=TV").get_json()) == 1
    assert finecim_client.get("/api/segment/ucty/kampane?media_typ=Print").get_json() == []


def test_produkty_include_attributes_and_company(finecim_client):
    produkty = finecim_client.get("/api/segment/ucty/produkty").get_json()
    assert len(produkty) == 1
    p = produkty[0]
    assert p["atributy"][0] == {"section": "Aktuální verze", "name": "iOS (verze)", "value": "26.4.51"}
    assert p["atributy_mapa"] == {"iOS (verze)": "26.4.51", "Android (verze)": "7.1"}
    assert p["spolecnost"]["id"] == "ceska_sporitelna"
    assert p["spolecnost_nazev"] == "Česká spořitelna"
    assert p["produktova_linie_nazev"] == "Mobilní aplikace"


def test_mystery_includes_pdf(finecim_client):
    shops = finecim_client.get("/api/segment/ucty/mystery-shopping").get_json()
    assert len(shops) == 1
    assert shops[0]["pdf_url"] == "https://www.finecim.cz/media/pdf/open?itemId=5"
    assert shops[0]["prilohy"][0]["nazev"] == "Zpráva"
    assert shops[0]["spolecnost_nazev"] == "Česká spořitelna"


def test_executive_summary_with_entries(finecim_client):
    rows = finecim_client.get("/api/segment/ucty/executive-summary").get_json()
    assert len(rows) == 1
    es = rows[0]
    assert (es["rok"], es["mesic"], es["nazev"]) == (2026, 6, "červen 2026")
    assert es["telo"].startswith("- [mBank mění ceník](")
    assert [p["id"] for p in es["polozky"]] == ["fc-es-entry-101", "fc-es-entry-102"]
    assert es["polozky"][0]["clanek_url"] == f"{FC}/news/43573"
    assert es["polozky"][0]["clanek_existuje"] is True
    assert es["polozky"][1]["clanek_existuje"] is False
    assert es["polozky"][1]["text"] == "Shrnutí 2"
    # rows without url/typ (stored before those columns) still expose the clanek link
    assert es["polozky"][0]["typ"] is None
    assert es["polozky"][0]["url"] == f"{FC}/news/43573"


def test_executive_summary_entries_expose_url_and_typ(finecim_client, seeded_db):
    db = Database(seeded_db.db_path)  # the fixture closed its connection
    db.upsert_executive_summary(
        {"id": "fc-es-13", "segment_id": "ucty", "rok": 2026, "mesic": 7, "nazev": "červenec 2026"},
        [
            {"entry_id": 201, "clanek_id": "fc-news-43573", "nazev": "mBank mění ceník", "text": "N",
             "url": f"{FC}/news/43573", "typ": "news"},
            {"entry_id": 202, "clanek_id": None, "nazev": "Kampaň Air Bank", "text": "K",
             "url": f"{FC}/campaign/4695", "typ": "campaign"},
            {"entry_id": 203, "clanek_id": None, "nazev": "Mystery", "text": "M",
             "url": f"{FC}/mystery-shopping/5", "typ": "mystery-shopping"},
            {"entry_id": 204, "clanek_id": "fc-news-77", "nazev": "Nestažená", "text": "S",
             "url": f"{FC}/news/77", "typ": "news"},
        ],
    )
    db.close()
    rows = finecim_client.get("/api/segment/ucty/executive-summary").get_json()
    es = next(r for r in rows if r["id"] == "fc-es-13")
    by_id = {p["id"]: p for p in es["polozky"]}
    assert list(by_id) == ["fc-es-entry-201", "fc-es-entry-202", "fc-es-entry-203", "fc-es-entry-204"]

    news = by_id["fc-es-entry-201"]
    assert news["typ"] == "news" and news["url"] == f"{FC}/news/43573"
    assert news["clanek_url"] == f"{FC}/news/43573" and news["clanek_existuje"] is True

    campaign = by_id["fc-es-entry-202"]
    assert campaign["typ"] == "campaign" and campaign["url"] == f"{FC}/campaign/4695"
    assert campaign["clanek_url"] is None and campaign["clanek_existuje"] is False

    mystery = by_id["fc-es-entry-203"]
    assert mystery["typ"] == "mystery-shopping" and mystery["url"] == f"{FC}/mystery-shopping/5"
    assert mystery["clanek_existuje"] is False

    missing = by_id["fc-es-entry-204"]
    assert missing["clanek_existuje"] is False and missing["url"] == f"{FC}/news/77"


def test_spolecnost_detail_profile_attachments_and_counts(finecim_client):
    resp = finecim_client.get("/api/spolecnost/ceska_sporitelna")
    assert resp.status_code == 200
    d = resp.get_json()
    assert d["popis"] == "Největší banka"
    assert d["pocet_pobocek"] == 346
    assert d["ico"] == "45244782"
    assert d["socialni_site"]["web"] == "https://www.csas.cz"
    assert d["predstavenstvo"][0]["jmeno"] == "Tomáš Salomon"
    assert d["predstavenstvo"][0]["role"] == "předseda"
    assert d["finecim_subject_id"] == 11
    assert d["logo_url"] == "https://www.finecim.cz/media/image/default/11"
    assert [p["nazev"] for p in d["prilohy"]] == [
        "Ceska-sporitelna-vyrocni-zprava-2024", "Ceska-sporitelna-vyrocni-zprava-2023",
    ]
    assert d["pocty"] == {
        "clanky": 1, "kampane": 1, "mystery_shopping": 1, "produkty": 1, "prilohy": 2,
    }
    assert d["kampane"][0]["kreativy"][0]["id"] == "fc-creative-2"
    assert d["produkty"][0]["atributy_mapa"]["iOS (verze)"] == "26.4.51"


def test_spolecnost_detail_includes_items_related_via_vazby(finecim_client):
    d = finecim_client.get("/api/spolecnost/mbank").get_json()
    assert [c["id"] for c in d["clanky"]] == ["fc-news-43573"]
    assert d["pocty"]["clanky"] == 1
    assert d["prilohy"] == []
    assert finecim_client.get("/api/spolecnost/nope").status_code == 404


def test_finecim_status_route(finecim_client):
    resp = finecim_client.get("/api/finecim/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["sync"][0]["entity"] == "news"
    assert data["sync"][0]["newest_id"] == 43573
    assert data["posledni_uspech"] == "2026-11-05T08:01:00"
    pocty = data["pocty"]
    assert pocty["clanky"] == 2
    assert pocty["kampane_kreativy"] == 2
    assert pocty["executive_summary_polozky"] == 2
    assert pocty["finecim_prilohy"] == 3
    assert pocty["finecim_vazby"] == 2


def test_sanitize_html_allow_list():
    out = sanitize_html(
        '<div class="x"><p onclick="evil()">A<img src="javascript:x" alt="i"></p>'
        '<iframe src="https://e.invalid"></iframe><a href="//evil.invalid">b</a></div>'
    )
    assert out == '<p>A<img alt="i"/></p><a>b</a>'
