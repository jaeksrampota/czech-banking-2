"""Tests for src.finecim.parsers against the trimmed live pages in tests/fixtures/finecim/."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from src.finecim.parsers import (
    CZECH_MONTHS,
    ParseError,
    parse_campaign_creatives,
    parse_campaign_detail,
    parse_campaign_list,
    parse_date_cz,
    parse_executive_summary_detail,
    parse_executive_summary_list,
    parse_item_url,
    parse_mystery_detail,
    parse_mystery_list,
    parse_news_detail,
    parse_news_list,
    parse_pagination,
    parse_product_detail,
    parse_product_list,
    parse_product_parameters,
    parse_subject_detail,
    parse_subject_list,
)

FIXTURES = Path(__file__).parent / "fixtures" / "finecim"
BASE = "https://www.finecim.cz"
UCTY = f"{BASE}/cz/domena/ucty"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- helpers


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"{UCTY}/news/43573", {"segment": "ucty", "entity": "news", "id": 43573}),
        ("/cz/domena/ucty/campaign/4695?do=favorite", {"segment": "ucty", "entity": "campaign", "id": 4695}),
        (
            f"{BASE}/cz/domena/sporeni/mystery-shopping/401",
            {"segment": "sporeni", "entity": "mystery-shopping", "id": 401},
        ),
        (f"{UCTY}/produkt/3936", {"segment": "ucty", "entity": "produkt", "id": 3936}),
        (f"{UCTY}/subjekt/120", {"segment": "ucty", "entity": "subjekt", "id": 120}),
        (
            f"{BASE}/cz/domena/bankovni-trh/executive-summary/10664",
            {"segment": "bankovni-trh", "entity": "executive-summary", "id": 10664},
        ),
        (f"{UCTY}/news?step=96&page=2", {"segment": "ucty", "entity": "news", "id": None}),
    ],
)
def test_parse_item_url(url, expected):
    assert parse_item_url(url) == expected


def test_parse_item_url_rejects_non_domain_urls():
    with pytest.raises(ParseError):
        parse_item_url(f"{BASE}/cz/tags/detail/99")
    with pytest.raises(ParseError):
        parse_item_url("")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("05.11.2026", "2026-11-05"),
        ("6. 8. 2026", "2026-08-06"),
        ("  20. 7. 2026 ", "2026-07-20"),
        ("začátek: 01.11.2026", "2026-11-01"),
        ("Datum aktualizace:\xa002.11.2026", "2026-11-02"),
        ("4. listopad 2026", "2026-11-04"),
        ("4. listopadu 2026", "2026-11-04"),
        ("2026-11-05", "2026-11-05"),
        ("31.02.2026", None),
        ("26.4.51", None),
        ("bez data", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_date_cz(text, expected):
    assert parse_date_cz(text) == expected


def test_czech_months_cover_the_year():
    assert sorted(CZECH_MONTHS.values()) == list(range(1, 13))
    assert CZECH_MONTHS["leden"] == 1 and CZECH_MONTHS["prosinec"] == 12


# --------------------------------------------------------------------------- page-type guard


@pytest.mark.parametrize(
    "parser",
    [
        parse_news_detail,
        parse_campaign_detail,
        parse_mystery_detail,
        parse_product_detail,
        parse_subject_detail,
        parse_executive_summary_detail,
        parse_news_list,
        parse_executive_summary_list,
    ],
)
def test_signin_page_raises_parse_error(parser):
    with pytest.raises(ParseError):
        parser(load("signin.html"), f"{UCTY}/news/43573")


def test_signin_page_raises_for_html_only_parsers():
    with pytest.raises(ParseError):
        parse_product_parameters(load("signin.html"))
    with pytest.raises(ParseError):
        parse_pagination(load("signin.html"))
    with pytest.raises(ParseError):
        parse_campaign_creatives(load("signin.html"), f"{UCTY}/campaign/4695")


def test_page_without_content_raises():
    with pytest.raises(ParseError):
        parse_news_detail("<html><body><p>nothing</p></body></html>", f"{UCTY}/news/1")
    with pytest.raises(ParseError):
        parse_news_detail("", f"{UCTY}/news/1")


def test_wrong_detail_type_raises():
    with pytest.raises(ParseError):
        parse_campaign_detail(load("detail_news.html"), f"{UCTY}/campaign/1")


def test_minimal_pages_give_empty_results():
    html = (
        '<html><body><div id="kt_content"><div class="row" id="snippet--listingItems"></div>'
        '<div class="row" id="snippet--listing"></div>'
        '<div id="snippet--content"><div class="row"></div></div></div></body></html>'
    )
    assert parse_news_list(html, f"{UCTY}/news") == []
    assert parse_campaign_list(html, f"{UCTY}/campaign") == []
    assert parse_mystery_list(html, f"{UCTY}/mystery-shopping") == []
    assert parse_product_list(html, f"{UCTY}/produkty") == []
    assert parse_subject_list(html, f"{UCTY}/subjekty") == []
    assert parse_product_parameters(html) == []
    assert parse_pagination(html) == {"total": None, "step": None, "page": 1, "last_page": 1}


def test_detail_with_missing_optional_fields():
    html = (
        '<html><body><div id="kt_content"><div class="ecim-widget-article-detail">'
        '<h3 class="ecim-widget-article-detail__title">Jen titulek</h3></div></div></body></html>'
    )
    item = parse_news_detail(html, f"{UCTY}/news/5")
    assert item["id"] == 5 and item["title"] == "Jen titulek"
    assert item["date"] is None and item["perex"] is None and item["body_html"] is None
    assert item["badges"] == [] and item["tags"] == [] and item["news_types"] == []
    assert item["related_subjects"] == [] and item["images"] == []


# --------------------------------------------------------------------------- pagination


def test_parse_pagination_first_page():
    assert parse_pagination(load("list_news.html")) == {
        "total": 4722,
        "step": 12,
        "page": 1,
        "last_page": 394,
    }


def test_parse_pagination_page2_step96():
    assert parse_pagination(load("list_news_page2_step96.html")) == {
        "total": 4722,
        "step": 96,
        "page": 2,
        "last_page": 50,
    }


@pytest.mark.parametrize(
    ("name", "total", "last_page"),
    [("list_campaign.html", 419, 35), ("list_mystery.html", 131, 11), ("list_products.html", 203, 17)],
)
def test_parse_pagination_other_lists(name, total, last_page):
    pagination = parse_pagination(load(name))
    assert pagination["total"] == total
    assert pagination["last_page"] == last_page
    assert pagination["step"] == 12 and pagination["page"] == 1


# --------------------------------------------------------------------------- list pages


def test_parse_news_list():
    items = parse_news_list(load("list_news.html"), f"{UCTY}/news?step=96")
    assert [i["id"] for i in items] == [43573, 43568, 43566]
    first = items[0]
    assert first["segment"] == "ucty"
    assert first["url"] == f"{UCTY}/news/43573"
    assert first["title"].startswith("mBank mění svou mobilní aplikaci")
    assert first["date"] == "2026-11-05"
    assert first["badges"] == ["new"]
    assert first["annotation"].startswith("Klienti mBank mají od konce října 2026")
    assert first["tags"] == [
        {"id": 99, "name": "mobilní bankovnictví", "url": f"{BASE}/cz/tags/detail/99"},
        {"id": 762, "name": "Tisková zpráva mBank", "url": f"{BASE}/cz/tags/detail/762"},
    ]
    assert first["logo_url"] == f"{BASE}/media/image/default/57853?width=60&height=38"
    assert items[1]["title"] == "Aplikace KB+ překonala 1,8 mil. klientů"
    assert items[1]["date"] == "2026-11-04"
    assert len(items[1]["tags"]) == 3


def test_parse_news_list_page2():
    items = parse_news_list(load("list_news_page2_step96.html"), f"{UCTY}/news?step=96&page=2")
    assert [i["id"] for i in items] == [43194, 43179]
    assert items[1]["title"] == "Fio banka představila nový design platební karty Mastercard Business World"


def test_parse_campaign_list():
    items = parse_campaign_list(load("list_campaign.html"), f"{UCTY}/campaign")
    assert [i["id"] for i in items] == [4695, 4686, 4677]
    first = items[0]
    assert first["title"] == "Důvody, proč i banku můžete mít rádi"
    assert first["url"] == f"{UCTY}/campaign/4695"
    assert first["start_date"] == "2026-11-01"
    assert first["updated_date"] == "2026-11-02"
    assert first["badges"] == ["updated"]
    assert first["media_types"] == ["TV"]
    assert first["annotation"].startswith("Air Bank v televizní kampani")
    assert first["thumbnail_url"] == f"{BASE}/media/image/default/62333?width=140&height=140"
    # second card has no "aktualizace" line and no badge
    assert items[1]["start_date"] == "2026-10-05"
    assert items[1]["updated_date"] is None
    assert items[1]["badges"] == []
    assert items[2]["updated_date"] == "2026-10-05"


def test_parse_mystery_list():
    items = parse_mystery_list(load("list_mystery.html"), f"{UCTY}/mystery-shopping")
    assert [(i["id"], i["date"]) for i in items] == [
        (496, "2026-10-14"),
        (495, "2026-09-03"),
        (494, "2026-08-24"),
    ]
    assert items[0]["title"] == "Zmapování Minihry Formule George v mobilní aplikaci George"
    assert items[0]["url"] == f"{UCTY}/mystery-shopping/496"
    assert items[1]["annotation"].startswith("Privatbanka v květnu 2026 změnila název na Penta Bank")


def test_parse_product_list():
    items = parse_product_list(load("list_products.html"), f"{UCTY}/produkty")
    assert items[0]["id"] == 3936 and items[1]["id"] == 3934
    first = items[0]
    assert first["title"] == "Smart Banking"
    assert first["product_line"] == "Mobilní aplikace"
    assert first["customer_segment"] == "Fyzické osoby"
    assert first["annotation"] == "UniCredit Bank pro své klienty nabízí mobilní aplikaci Smart Banking."
    assert first["badges"] == []
    assert first["logo_url"] == f"{BASE}/media/image/default/51504?width=60&height=38"
    assert first["segment"] == "ucty"


def test_parse_subject_list():
    items = parse_subject_list(load("list_subjekty.html"), f"{UCTY}/subjekty")
    assert len(items) == 27
    by_id = {i["id"]: i for i in items}
    assert items[0] == {
        "id": 351,
        "segment": "ucty",
        "url": f"{UCTY}/subjekt/351",
        "name": "Penta Bank",
        "logo_url": f"{BASE}/media/image/default/60591?width=75&height=75",
    }
    assert by_id[120]["name"] == "Trinity Bank"
    assert by_id[52]["name"] == "mBank"
    # the "Bankovní trh" tile has a heading instead of a logo
    assert by_id[56]["name"] == "Bankovní trh" and by_id[56]["logo_url"] is None


_LIST_CASES = [
    (parse_news_list, "list_news.html", f"{UCTY}/news?step=96", "#snippet--listingItems"),
    (parse_campaign_list, "list_campaign.html", f"{UCTY}/campaign", "#snippet--listing"),
    (parse_mystery_list, "list_mystery.html", f"{UCTY}/mystery-shopping", "#snippet--listingItems"),
    (parse_product_list, "list_products.html", f"{UCTY}/produkty", "#snippet--listing"),
    (parse_subject_list, "list_subjekty.html", f"{UCTY}/subjekty", "#snippet--content .row"),
]
_LIST_IDS = ["news", "campaign", "mystery", "product", "subject"]


def _edit_container(name: str, selector: str, *, remove: bool) -> str:
    soup = BeautifulSoup(load(name), "lxml")
    container = soup.select_one(selector)
    assert container is not None and soup.find(id="kt_content") is not None
    if remove:
        container.decompose()
    else:
        container.clear()
    return str(soup)


@pytest.mark.parametrize(("parser", "fixture", "url", "selector"), _LIST_CASES, ids=_LIST_IDS)
def test_list_parsers_reject_a_page_without_the_listing_container(parser, fixture, url, selector):
    assert parser(load(fixture), url)  # the unmodified fixture has cards
    html = _edit_container(fixture, selector, remove=True)
    with pytest.raises(ParseError, match="listing container missing"):
        parser(html, url)


@pytest.mark.parametrize(("parser", "fixture", "url", "selector"), _LIST_CASES, ids=_LIST_IDS)
def test_list_parsers_return_empty_list_for_an_empty_container(parser, fixture, url, selector):
    html = _edit_container(fixture, selector, remove=False)
    assert parser(html, url) == []


# --------------------------------------------------------------------------- detail pages


def test_parse_news_detail():
    item = parse_news_detail(load("detail_news.html"), f"{UCTY}/news/43573")
    assert item["id"] == 43573 and item["segment"] == "ucty"
    assert item["url"] == f"{UCTY}/news/43573"
    assert item["title"].startswith("mBank mění svou mobilní aplikaci")
    assert item["date"] == "2026-11-05"
    assert item["badges"] == ["new"]
    assert item["news_types"] == ["produkty a služby", "tiskové zprávy"]
    assert item["perex"].startswith("Klienti mBank mají od konce října 2026")
    assert {"id": 99, "name": "mobilní bankovnictví", "url": f"{BASE}/cz/tags/detail/99"} in item["tags"]
    assert item["source_line"] == "Zdroj: cz.media.mbank.pl, 4. listopad 2026"
    assert item["images"] == []
    assert item["related_subjects"] == [{"id": 52, "name": "mBank", "url": f"{UCTY}/subjekt/52"}]
    assert item["related_products"] == [{"id": 3937, "name": "mBank CZ", "url": f"{UCTY}/produkt/3937"}]
    # "Mohlo by Vás také zajímat" is a recommendation widget, not "Související zprávy"
    assert item["related_news"] == []


def test_news_detail_body_is_sanitised():
    item = parse_news_detail(load("detail_news.html"), f"{UCTY}/news/43573")
    html = item["body_html"]
    assert html.startswith("<p>Při ztrátě platební karty")
    assert "<blockquote><p>„Chceme, aby" in html
    assert "<em>Zdroj: cz.media.mbank.pl" in html
    for forbidden in ("style=", "class=", "id=", "news-annotation-text", "\xa0", "<div"):
        assert forbidden not in html
    # perex is not repeated in the body
    assert "Klienti mBank mají od konce října 2026" not in html
    text = item["body_text"]
    paragraphs = text.split("\n\n")
    assert paragraphs[0].startswith("Při ztrátě platební karty nebo podezřelé transakci")
    assert paragraphs[2] == "Ztráta karty nebo podezřelá platba? mBank usnadňuje řešení problémů"
    assert paragraphs[-1] == "Zdroj: cz.media.mbank.pl, 4. listopad 2026"
    assert "<" not in text and "\n\n\n" not in text


def test_parse_campaign_detail():
    item = parse_campaign_detail(load("detail_campaign.html"), f"{UCTY}/campaign/4695")
    assert item["id"] == 4695 and item["segment"] == "ucty"
    assert item["title"] == "Důvody, proč i banku můžete mít rádi"
    assert item["created_date"] == "2026-11-01"
    assert item["updated_date"] == "2026-11-02"
    assert item["badges"] == ["updated"]
    assert item["campaign_types"] == ["Produktová", "Imageová"]
    assert item["annotation"].startswith("Air Bank v televizní kampani představuje důvody")
    assert item["key_visual_url"] == f"{BASE}/media/image/default/62334"
    assert item["media"] == [
        {
            "type": "TV",
            "count": 2,
            "creatives_url": (
                f"{UCTY}/campaign/4695?type=9&link=https%3A%2F%2Fwww.finecim.cz%2Fcz%2Fdomena%2Fucty"
                "%2Fcampaign%2F4695&do=campaignCreatives"
            ),
        }
    ]
    assert item["media"][0]["creatives_url"].endswith("do=campaignCreatives")
    assert [t["date"] for t in item["timeline"]] == ["2026-11-02", "2026-11-01"]
    assert item["timeline"][0]["text"].startswith('Air Bank v rámci spotu "Vše v aplikaci jednoduše"')
    assert "(20 s)" in item["timeline"][0]["text"]
    assert item["related_subjects"] == [{"id": 71, "name": "Air Bank", "url": f"{UCTY}/subjekt/71"}]
    assert [p["id"] for p in item["related_products"]] == [4054]
    assert [c["id"] for c in item["related_campaigns"]] == [4397, 4356, 4336]


def test_parse_campaign_creatives():
    events = parse_campaign_creatives(load("campaign_creatives.html"), f"{UCTY}/campaign/4695")
    assert len(events) == 2
    first = events[0]
    assert first["date"] == "2026-11-02"
    assert first["creative_id"] == 29123
    assert first["media_kind"] == "video"
    assert first["media_url"] == f"{BASE}/media/download/default/22755"
    assert first["media_url"].endswith("/media/download/default/22755")
    assert first["text"].startswith('Air Bank v rámci spotu "Vše v aplikaci jednoduše"')
    assert "\n\n" in first["text"]
    assert events[1]["creative_id"] == 29116 and events[1]["date"] == "2026-11-01"
    assert events[1]["media_url"].endswith("/22742")


def test_parse_campaign_creatives_image_and_empty():
    html = (
        '<div class="ecim-widget-campaign-event"><h3 class="kt-portlet__head-title">03.03.2026</h3>'
        '<div class="ecim-general-content"><p>Billboard</p><img src="/media/image/default/5"></div></div>'
    )
    assert parse_campaign_creatives(html, f"{UCTY}/campaign/1") == [
        {
            "creative_id": None,
            "date": "2026-03-03",
            "text": "Billboard",
            "media_url": f"{BASE}/media/image/default/5",
            "media_kind": "image",
        }
    ]
    assert parse_campaign_creatives("<div></div>", f"{UCTY}/campaign/1") == []


def test_parse_mystery_detail():
    item = parse_mystery_detail(load("detail_mystery.html"), f"{UCTY}/mystery-shopping/496")
    assert item["id"] == 496 and item["segment"] == "ucty"
    assert item["title"] == "Zmapování Minihry Formule George v mobilní aplikaci George"
    assert item["date"] == "2026-10-14"
    assert item["perex"].startswith("Česká spořitelna spustila v mobilní aplikaci George Minihru")
    assert item["pdf_url"] == f"{BASE}/media/pdf/open?itemId=22639"
    assert item["attachments"] == [
        {"name": "CS-Minihra-Formule", "url": f"{BASE}/media/pdf/open?itemId=22639"}
    ]
    assert item["tags"] == [{"id": 99, "name": "mobilní bankovnictví", "url": f"{BASE}/cz/tags/detail/99"}]
    assert '<img alt="" src="https://www.finecim.cz/media/image/default/62143"/>' in item["body_html"]
    assert "style=" not in item["body_html"]
    assert item["body_text"].startswith("Průběh Mystery Shoppingu")
    assert item["related_subjects"] == [{"id": 11, "name": "Česká spořitelna", "url": f"{UCTY}/subjekt/11"}]
    assert [p["id"] for p in item["related_products"]] == [4064]


def test_parse_product_detail():
    item = parse_product_detail(load("detail_product.html"), f"{UCTY}/produkt/3936")
    assert item["id"] == 3936 and item["segment"] == "ucty"
    assert item["title"] == "Smart Banking"
    assert item["product_line"] == "Mobilní aplikace"
    assert item["customer_segment"] == "Fyzické osoby"
    assert item["created_date"] == "2019-04-02"
    assert item["updated_date"] == "2026-09-01"
    assert item["annotation"] == "UniCredit Bank pro své klienty nabízí mobilní aplikaci Smart Banking."
    assert item["logo_url"] == f"{BASE}/media/image/default/51504?width=80&height=60"
    assert item["parameters_url"] == f"{UCTY}/produkty/parameters-new-window/3936"
    assert item["history_url"] == f"{UCTY}/produkty/history-new-window/3936"
    assert item["related_subjects"] == [{"id": 43, "name": "UniCredit Bank", "url": f"{UCTY}/subjekt/43"}]
    assert [n["id"] for n in item["related_news"]] == [43471, 43457, 43422]


def test_parse_product_parameters():
    rows = parse_product_parameters(load("product_parameters.html"))
    assert len(rows) == 12
    assert rows[0] == {"section": "Aktuální verze", "name": "iOS (verze)", "value": "26.4.51"}
    assert rows[1] == {"section": "Aktuální verze", "name": "iOS (datum aktualizace)", "value": "6. 8. 2026"}
    assert rows[3] == {
        "section": "Přihlášení",
        "name": "Touch ID",
        "value": "ano (Android) / ano (iOS se čtečkou otisků prstů)",
    }
    assert rows[-1] == {
        "section": "Hodnocení a dostupnost",
        "name": "Velikost aplikace (iOS)",
        "value": "708 MB",
    }
    sections = list(dict.fromkeys(r["section"] for r in rows))
    assert sections == ["Aktuální verze", "Přihlášení", "Hodnocení a dostupnost"]
    # the product detail page carries the same accordion
    assert parse_product_parameters(load("detail_product.html")) == rows


def test_parse_subject_detail():
    item = parse_subject_detail(load("detail_company.html"), f"{UCTY}/subjekt/120")
    assert item["id"] == 120 and item["segment"] == "ucty"
    assert item["name"] == "Trinity Bank"
    assert item["updated_date"] == "2025-08-01"
    assert item["logo_url"] == f"{BASE}/media/image/default/32549?width=80&height=45"
    assert item["legal_name"] == "Trinity Bank, a. s."
    assert item["ico"] == "25307835"
    assert item["address"] == "Celetná 969/40, Staré Město, 110 00 Praha 1"
    assert item["share_capital"] == "4 161 181 000 CZK"
    assert item["shareholder"] == "Trinity Bank, a. s."
    assert item["board"] == [
        {"name": "Ing. Dušan Benda", "role": "předseda představenstva"},
        {"name": "Ing. Jaroslav Končický", "role": "místopředseda představenstva"},
        {"name": "MVDr. Jan Černý", "role": "člen představenstva"},
        {"name": "Mgr. Petr Okrajek", "role": "člen představenstva"},
        {"name": "Mgr. Veronika Huml Válová", "role": "člen představenstva"},
    ]
    assert item["clients"] == 200000
    assert item["branches"] == 9
    assert item["atms"] is None
    assert item["social_links"]["facebook"] == "https://www.facebook.com/trinitybankcz"
    assert item["social_links"]["instagram"] == "https://www.instagram.com/trinitybankcz/"
    assert item["social_links"]["x"] == "https://x.com/trinitybankcz"
    assert item["social_links"]["linkedin"].startswith("https://www.linkedin.com/search/results/all/")
    assert item["social_links"]["youtube"] == "https://www.youtube.com/@trinitybank9055"
    assert item["social_links"]["web"] == "https://www.trinitybank.cz/"
    assert item["description_text"].startswith("Trinity Bank, dříve známá jako Moravský Peněžní Ústav (MPU)")
    assert item["description_text"].count("\n\n") == 2
    assert "Základní informace" not in item["description_text"]
    assert "Identifikační číslo" not in (item["description_html"] or "")
    assert item["description_html"].startswith("<p><strong>Trinity Bank")
    assert item["attachments"] == [
        {"name": "trinitybank-vz-2024-1", "url": f"{BASE}/media/pdf/open?itemId=20434"},
        {"name": "trinitybank-vz2023", "url": f"{BASE}/media/pdf/open?itemId=20435"},
        {"name": "TB-vyrocni-zprava-2022", "url": f"{BASE}/media/pdf/open?itemId=16166"},
    ]
    # the fixture keeps 3 items per right-column widget
    assert item["related_counts"] == {"news": 3, "campaigns": 3, "mystery": 3, "products": 3}
    assert item["related_ids"] == {
        "news": [43541, 43539, 43495],
        "campaigns": [4693, 4594, 4515],
        "mystery": [409, 401, 237],
        "products": [4590, 4141, 4303],
    }


def test_subject_detail_kpi_line_with_all_numbers():
    html = (
        '<html><body><div id="kt_content"><div class="ecim-widget-subject-detail">'
        '<h3 class="ecim-widget-subject-detail__title">Česká spořitelna</h3>'
        '<div class="ecim-general-content">'
        "<p>Popis banky.</p>"
        "<p><strong>Základní informace o společnosti:</strong></p>"
        "<p><strong>Identifikační číslo:</strong>&nbsp;452&nbsp;44&nbsp;782<br>"
        "<strong>Představenstvo:</strong> Tomáš Salomon (předseda)<br>Jan Novák</p>"
        "<p>4 600 000 klientů &nbsp; 346 poboček &nbsp; 1 625 bankomatů</p>"
        "</div></div></div></body></html>"
    )
    item = parse_subject_detail(html, f"{UCTY}/subjekt/11")
    assert item["ico"] == "45244782"
    assert item["clients"] == 4600000 and item["branches"] == 346 and item["atms"] == 1625
    assert item["board"] == [
        {"name": "Tomáš Salomon", "role": "předseda"},
        {"name": "Jan Novák", "role": None},
    ]
    assert item["description_text"] == "Popis banky."
    assert item["social_links"] == {
        "facebook": None,
        "x": None,
        "instagram": None,
        "linkedin": None,
        "youtube": None,
        "web": None,
    }
    assert item["related_counts"] == {"news": 0, "campaigns": 0, "mystery": 0, "products": 0}
    assert item["attachments"] == [] and item["legal_name"] is None


# --------------------------------------------------------------------------- executive summary


def test_parse_executive_summary_list():
    items = parse_executive_summary_list(load("list_executive_summary.html"), f"{UCTY}/executive-summary")
    assert {i["year"] for i in items} == {2026, 2025}
    first = items[0]
    assert first == {
        "id": 10664,
        "segment": "ucty",
        "url": f"{UCTY}/executive-summary/10664",
        "year": 2026,
        "month": 6,
        "month_name": "červen",
    }
    assert [(i["id"], i["month"]) for i in items if i["year"] == 2026] == [(10664, 6), (10677, 5)]
    months_2025 = [i["month"] for i in items if i["year"] == 2025]
    assert months_2025 == [9, 8, 7, 6, 5, 4, 3, 2, 1]
    assert len(items) == 11


def test_parse_executive_summary_detail():
    item = parse_executive_summary_detail(
        load("detail_executive_summary.html"), f"{UCTY}/executive-summary/10664"
    )
    assert item["id"] == 10664 and item["segment"] == "ucty"
    assert item["month_name"] == "červen"
    entries = item["entries"]
    assert len(entries) == 4
    assert entries[0]["entry_id"] == 45835
    assert entries[0]["news_id"] == 42857
    assert entries[0]["news_url"] == f"{BASE}/cz/domena/bankovni-trh/news/42857"
    assert entries[0]["title"] == "Digital Share of Reach Tracker 05/26"
    assert entries[0]["text"].startswith("Aktualizovaná verze pravidelného reportu Digital Share of Reach")
    assert [e["entry_id"] for e in entries] == [45835, 45856, 45834, 45846]
    assert [e["news_id"] for e in entries] == [42857, 42712, 42862, 42717]
    assert [e["entity"] for e in entries] == ["news"] * 4
    assert entries[0]["item_url"] == f"{BASE}/cz/domena/bankovni-trh/news/42857"
    assert all(e["item_url"] == e["news_url"] for e in entries)


def _summary_entry(entry_id: int, href: str, title: str) -> str:
    return (
        '<div class="ecim-widget-summary"><h3 class="ecim-widget-summary__title">'
        f'<a href="{href}">{title}</a></h3>'
        f'<input class="es-entry-picker" type="checkbox" value="{entry_id}">'
        f'<p class="es-annotation-text">Text {entry_id}</p></div>'
    )


def test_executive_summary_entries_link_to_campaigns_mystery_and_products():
    extra = (
        _summary_entry(1, "/cz/domena/ucty/campaign/4695", "Kampaň Air Bank")
        + _summary_entry(2, f"{BASE}/cz/domena/sporeni/mystery-shopping/401", "Mystery spoření")
        + _summary_entry(3, "/cz/domena/ucty/produkt/3936", "Smart Banking")
        + _summary_entry(4, "/cz/domena/ucty/subjekt/120", "Trinity Bank")
        + _summary_entry(5, "https://example.com/report", "Externí odkaz")
    )
    html = load("detail_executive_summary.html")
    marker = '<div class="ecim-widget-summary'
    position = html.index(marker)
    html = html[:position] + extra + html[position:]
    entries = parse_executive_summary_detail(html, f"{UCTY}/executive-summary/10664")["entries"]
    by_id = {e["entry_id"]: e for e in entries}
    assert len(entries) == 9

    campaign = by_id[1]
    assert campaign["entity"] == "campaign"
    assert campaign["news_id"] is None
    assert campaign["item_url"] == f"{UCTY}/campaign/4695"
    assert campaign["news_url"] == campaign["item_url"]
    assert campaign["title"] == "Kampaň Air Bank" and campaign["text"] == "Text 1"

    mystery = by_id[2]
    assert mystery["entity"] == "mystery-shopping" and mystery["news_id"] is None
    assert mystery["item_url"] == f"{BASE}/cz/domena/sporeni/mystery-shopping/401"

    product = by_id[3]
    assert product["entity"] == "produkt" and product["news_id"] is None
    assert product["item_url"] == f"{UCTY}/produkt/3936"

    for unknown in (by_id[4], by_id[5]):
        assert unknown["entity"] is None and unknown["news_id"] is None
    assert by_id[5]["item_url"] == "https://example.com/report"

    news = by_id[45835]
    assert news["entity"] == "news" and news["news_id"] == 42857


# --------------------------------------------------------------------------- hardening


def _page(inner: str) -> str:
    return f'<html><body><div id="kt_content">{inner}</div></body></html>'


@pytest.mark.parametrize("html", ["", "   \n\t  ", "<div></div>", "<p>Žádné kreativy</p>"])
def test_campaign_creatives_empty_fragment_gives_empty_list(html):
    assert parse_campaign_creatives(html, f"{UCTY}/campaign/1") == []


def test_campaign_creatives_still_rejects_signin_page():
    with pytest.raises(ParseError):
        parse_campaign_creatives(load("signin.html"), f"{UCTY}/campaign/1")


def test_sanitiser_keeps_word_breaks_from_whitespace_only_inline_tags():
    html = _page(
        '<div class="ecim-widget-article-detail"><div class="ecim-general-content">'
        "<p>Banka<strong> </strong>spustila<em>&nbsp;</em>novou<span>  </span>aplikaci"
        "<b></b>dnes<i>\n</i>ráno<u> </u>konec.</p>"
        "<p><strong>&nbsp;</strong></p>"
        "</div></div>"
    )
    item = parse_news_detail(html, f"{UCTY}/news/7")
    assert item["body_text"] == "Banka spustila novou aplikacidnes ráno konec."
    assert item["body_html"] == "<p>Banka spustila novou aplikacidnes ráno konec.</p>"


def test_sanitiser_drops_unsafe_url_schemes():
    html = _page(
        '<div class="ecim-widget-article-detail"><div class="ecim-general-content"><p>'
        '<a href="javascript:alert(1)">js</a> <a href=" JaVa\tScRiPt:alert(1)">js2</a> '
        '<a href="vbscript:msgbox(1)">vb</a> <a href="data:text/html;base64,PHNjcmlwdD4=">data</a> '
        '<a href="tel:+420123">tel</a> <a href="mailto:info@example.cz">mail</a> '
        '<a href="/cz/tags/detail/5">rel</a> <a href="https://example.cz/x">abs</a> '
        '<a href="//cdn.example.cz/y">proto</a>'
        '<img src="data:image/png;base64,AAAA"><img src="/media/image/default/1">'
        "</p></div></div>"
    )
    item = parse_news_detail(html, f"{UCTY}/news/8")
    body = item["body_html"]
    for bad in ("javascript", "JaVa", "vbscript", "data:", "tel:"):
        assert bad not in body
    assert '<a href="mailto:info@example.cz">mail</a>' in body
    assert f'<a href="{BASE}/cz/tags/detail/5">rel</a>' in body
    assert '<a href="https://example.cz/x">abs</a>' in body
    assert '<a href="https://cdn.example.cz/y">proto</a>' in body
    assert item["images"] == [f"{BASE}/media/image/default/1"]
    # the anchors without a safe href keep their text
    assert "<a>js</a>" in body and "<a>vb</a>" in body


def test_news_date_reads_the_date_element_not_a_distractor():
    html = load("detail_news.html").replace(
        '<ul class="ecim-widget-article-detail__badges">',
        '<p class="ecim-widget-article-detail__version">verze 26.4.51, vydáno 01.01.2020</p>'
        '<ul class="ecim-widget-article-detail__badges"><li>26.4.51</li>',
        1,
    )
    assert "01.01.2020" in html
    assert parse_news_detail(html, f"{UCTY}/news/43573")["date"] == "2026-11-05"


def test_mystery_date_reads_the_date_element_not_a_distractor():
    html = load("detail_mystery.html").replace(
        '<div class="ecim-widget-mystery-detail__info">',
        '<div class="ecim-widget-mystery-detail__info"><span>Aplikace 26.4.51 ze dne 01.01.2020</span>',
        1,
    )
    assert "01.01.2020" in html
    assert parse_mystery_detail(html, f"{UCTY}/mystery-shopping/496")["date"] == "2026-10-14"


def test_mystery_date_from_info_block_without_date_element():
    html = _page(
        '<div class="ecim-widget-mystery-detail">'
        '<h3 class="ecim-widget-mystery-detail__title">MS</h3>'
        '<div class="ecim-widget-mystery-detail__info"><ul><li>01.01.2020</li></ul>'
        "<p>Verze 26.4.51 Datum: 14.10.2026</p></div></div>"
    )
    assert parse_mystery_detail(html, f"{UCTY}/mystery-shopping/1")["date"] == "2026-10-14"


def test_campaign_and_product_dates_come_from_the_strong_after_the_label():
    campaign = (
        load("detail_campaign.html")
        .replace(
            'Datum vytvoření: <strong class="kt-font-success">01.11.2026</strong>',
            "<strong>26.4.51</strong> <span>01.01.2020</span> Datum vytvoření: "
            '<strong class="kt-font-success">01.11.2026</strong>',
            1,
        )
        .replace(
            'Datum aktualizace: <strong class="kt-font-warning">02.11.2026</strong>',
            '<b>03.03.2021</b> Datum&nbsp;aktualizace: <strong class="kt-font-warning">02.11.2026</strong>',
            1,
        )
    )
    assert campaign.count("01.01.2020") == 1 and campaign.count("03.03.2021") == 1
    item = parse_campaign_detail(campaign, f"{UCTY}/campaign/4695")
    assert item["created_date"] == "2026-11-01"
    assert item["updated_date"] == "2026-11-02"

    product = load("detail_product.html").replace(
        'Datum vytvoření: <strong class="kt-font-success">02.04.2019</strong>',
        "<span>iOS 26.4.51 / 05.05.2015</span> Datum vytvoření: "
        '<strong class="kt-font-success">02.04.2019</strong>',
        1,
    )
    assert "05.05.2015" in product
    item = parse_product_detail(product, f"{UCTY}/produkt/3936")
    assert item["created_date"] == "2019-04-02"
    assert item["updated_date"] == "2026-09-01"


def test_related_portlet_titles_ignore_case_whitespace_and_counts():
    html = (
        load("detail_company.html")
        .replace("Související zprávy\n", "  SOUVISEJÍCÍ\n   zprávy  (4075)\n", 1)
        .replace("Související kampaně", "související kampaně (200)", 1)
        .replace("Související Mystery Shopping", "Související mystery\xa0shopping ( 25 )", 1)
        .replace("Související produkty", "Související Produkty (57)", 1)
    )
    assert "(4075)" in html and "(200)" in html and "( 25 )" in html and "(57)" in html
    item = parse_subject_detail(html, f"{UCTY}/subjekt/120")
    assert item["related_ids"] == {
        "news": [43541, 43539, 43495],
        "campaigns": [4693, 4594, 4515],
        "mystery": [409, 401, 237],
        "products": [4590, 4141, 4303],
    }
    # the count in the title is the real total; the portlet only lists a few items
    assert item["related_counts"] == {"news": 4075, "campaigns": 200, "mystery": 25, "products": 57}

    product = load("detail_product.html").replace("Související zprávy", "SOUVISEJÍCÍ ZPRÁVY (12)", 1)
    assert [n["id"] for n in parse_product_detail(product, f"{UCTY}/produkt/3936")["related_news"]] == [
        43471,
        43457,
        43422,
    ]


def test_subject_social_links_from_text_links():
    html = _page(
        '<div class="ecim-widget-subject-detail">'
        '<h3 class="ecim-widget-subject-detail__title">Banka</h3>'
        '<div class="ecim-general-content">'
        '<p>Popis banky, viz <a href="https://www.cnb.cz/cs/">ČNB</a> a '
        '<a href="https://www.mesec.cz/">Měšec</a>.</p>'
        '<p><a href="https://www.facebook.com/banka">Facebook</a> | '
        '<a href="https://twitter.com/banka">Twitter</a> | '
        '<a href="https://instagram.com/banka">Instagram</a> | '
        '<a href="https://cz.linkedin.com/company/banka">LinkedIn</a> | '
        '<a href="https://youtu.be/abc">YouTube</a> | '
        '<a href="https://www.banka.cz/">www.banka.cz</a></p>'
        "</div></div>"
    )
    item = parse_subject_detail(html, f"{UCTY}/subjekt/9")
    assert item["social_links"] == {
        "facebook": "https://www.facebook.com/banka",
        "x": "https://twitter.com/banka",
        "instagram": "https://instagram.com/banka",
        "linkedin": "https://cz.linkedin.com/company/banka",
        "youtube": "https://youtu.be/abc",
        "web": "https://www.banka.cz/",
    }
    # the links-only paragraph is not part of the description
    assert item["description_text"] == "Popis banky, viz ČNB a Měšec."


def test_subject_web_link_is_not_guessed_from_a_paragraph_with_several_sites():
    html = _page(
        '<div class="ecim-widget-subject-detail">'
        '<h3 class="ecim-widget-subject-detail__title">Banka</h3>'
        '<div class="ecim-general-content">'
        '<p><a href="https://www.facebook.com/banka">Facebook</a> '
        '<a href="https://www.banka.cz/">Banka</a> <a href="https://www.jina.cz/">Jiná</a></p>'
        '<p>Podle <a href="https://www.cnb.cz/">ČNB</a> je banka stabilní.</p>'
        "</div></div>"
    )
    links = parse_subject_detail(html, f"{UCTY}/subjekt/9")["social_links"]
    assert links["facebook"] == "https://www.facebook.com/banka"
    assert links["web"] is None


def test_subject_kpis_take_the_number_right_before_each_keyword():
    html = _page(
        '<div class="ecim-widget-subject-detail">'
        '<h3 class="ecim-widget-subject-detail__title">Banka</h3>'
        '<div class="ecim-general-content">'
        "<p>Popis.</p>"
        "<p><strong>Základní informace o společnosti:</strong></p>"
        "<p>Banka působí od roku 1992, v roce 2025 200 000+ klientů, 2024 12 poboček "
        "a k 31. 12. 2025 celkem 1.625 bankomatů.</p>"
        "</div></div>"
    )
    item = parse_subject_detail(html, f"{UCTY}/subjekt/9")
    assert item["clients"] == 200000
    assert item["branches"] == 12
    assert item["atms"] == 1625

    html2 = html.replace("1.625 bankomatů", "4,6 mil. klientů a 46 bankomatů").replace(
        "200 000+ klientů", "zaměstnanců 300"
    )
    item = parse_subject_detail(html2, f"{UCTY}/subjekt/9")
    assert item["clients"] == 4600000 and item["atms"] == 46


# Česká spořitelna-style profile (SCRAPER-DESIGN.md 1.3): <strong>Label:</strong> value<br> pairs,
# IČO with spaces, board members with roles in parentheses separated by <br> and nbsp runs.
_NB = "&nbsp;"
CS_PROFILE = _page(
    '<div class="ecim-widget-subject-detail">'
    '<h3 class="ecim-widget-subject-detail__title">Česká spořitelna</h3>'
    '<div class="ecim-widget-subject-detail__date">Aktualizováno: <strong>15.09.2026</strong></div>'
    '<div class="ecim-general-content">'
    '<p style="text-align: justify;"><strong>Česká spořitelna</strong> byla založena v roce 1825; '
    "v roce 2024 vykázala zisk 21 mld. Kč.</p>"
    f"<p>{_NB}</p>"
    '<p style="text-align: right;"><a href="https://www.facebook.com/ceskasporitelna" target="_blank">'
    '<img alt="" src="/media/image/default/1"></a><a href="https://www.csas.cz/" target="_blank">'
    '<img alt="" src="/media/image/default/2"></a></p>'
    f"<p><strong><u>Základní informace o společnosti</u>:{_NB * 6}</strong><strong>{_NB * 8}</strong></p>"
    f"<p><strong>Obchodní firma:</strong>{_NB}Česká spořitelna, a.s.<br>\n"
    f"<strong>Identifikační číslo:</strong>{_NB}452{_NB}44{_NB}782<br>\n"
    f"<strong>Sídlo</strong>: Praha 4, Budějovická 1518/13a,b, PSČ 140{_NB}00</p>"
    f"<p><span><strong>Základní kapitál:</strong></span>{_NB}15 200 000 000 Kč<br>\n"
    "<strong>Akcionář: </strong>Erste Group Bank AG (99,46 %)</p>"
    "<p><strong>Představenstvo:</strong><br>\n"
    f"{_NB * 16}Tomáš Salomon (předseda představenstva){_NB * 8}Pavel Kráčmar{_NB}(místopředseda)<br>\n"
    f"{_NB * 16}Ing. Jan Novák{_NB * 6}Petr Dvořák (člen{_NB}představenstva)<br>\n"
    f"<strong>{_NB * 20}</strong></p>"
    f"<p><strong>{_NB * 10}<span>4 600 000 klientů </span>{_NB * 8}<span>{_NB}346 poboček</span>"
    f"{_NB * 8}<span>1 625 bankomatů</span></strong></p>"
    "</div></div>"
)


def test_parse_subject_detail_ceska_sporitelna_layout():
    item = parse_subject_detail(CS_PROFILE, f"{UCTY}/subjekt/11")
    assert item["name"] == "Česká spořitelna"
    assert item["updated_date"] == "2026-09-15"
    assert item["legal_name"] == "Česká spořitelna, a.s."
    assert item["ico"] == "45244782"
    assert item["address"] == "Praha 4, Budějovická 1518/13a,b, PSČ 140 00"
    assert item["share_capital"] == "15 200 000 000 Kč"
    assert item["shareholder"] == "Erste Group Bank AG (99,46 %)"
    assert item["board"] == [
        {"name": "Tomáš Salomon", "role": "předseda představenstva"},
        {"name": "Pavel Kráčmar", "role": "místopředseda"},
        {"name": "Ing. Jan Novák", "role": None},
        {"name": "Petr Dvořák", "role": "člen představenstva"},
    ]
    assert (item["clients"], item["branches"], item["atms"]) == (4600000, 346, 1625)
    assert item["social_links"]["facebook"] == "https://www.facebook.com/ceskasporitelna"
    assert item["social_links"]["web"] == "https://www.csas.cz/"
    assert item["description_text"].startswith("Česká spořitelna byla založena v roce 1825")
    assert "Základní informace" not in item["description_text"]


# --------------------------------------------------------------------------- pagination fallbacks


def _pager(links: str, footer: str = "") -> str:
    return _page(
        '<div class="kt-pagination kt-pagination--brand"><ul class="kt-pagination__links">'
        f"{links}</ul>{footer}</div>"
    )


def _link(page: int, *, active: bool = False) -> str:
    cls = ' class="kt-pagination__link--active"' if active else ""
    href = f"/cz/domena/ucty/news?step=12&amp;page={page}" if page > 1 else "/cz/domena/ucty/news?step=12"
    return f'<li><a{cls} href="{href}"> {page} </a></li>'


def test_pagination_last_page_from_highest_numbered_link():
    links = (
        _link(1)
        + _link(2, active=True)
        + _link(3)
        + _link(4)
        + _link(5)
        + '<li><a href="/cz/domena/ucty/news?step=12&amp;page=99">...</a></li>'
        + '<li class="kt-pagination__link--prev"><a href="/cz/domena/ucty/news?step=12&amp;page=3">'
        '<i class="fa fa-angle-right"></i></a></li>'
    )
    assert parse_pagination(_pager(links)) == {"total": None, "step": 12, "page": 2, "last_page": 5}


def test_pagination_last_page_from_total_and_step():
    footer = '<span class="m-datatable__pager-detail">Zobrazeno 1 - 12 z 131</span>'
    assert parse_pagination(_pager("", footer)) == {"total": 131, "step": 12, "page": 1, "last_page": 11}
    links = '<li><a href="/cz/domena/ucty/news?step=12&amp;page=7">...</a></li>'
    assert parse_pagination(_pager(links, footer))["last_page"] == 11


def test_pagination_numbered_links_take_priority_over_total_and_step():
    footer = '<span class="m-datatable__pager-detail">Zobrazeno 1 - 12 z 4720</span>'
    links = _link(1, active=True) + _link(2) + _link(3) + _link(4) + _link(5)
    assert parse_pagination(_pager(links, footer)) == {"total": 4720, "step": 12, "page": 1, "last_page": 5}


def test_pagination_last_page_defaults_to_one():
    assert parse_pagination(_pager("")) == {"total": None, "step": None, "page": 1, "last_page": 1}
    links = '<li><a href="/cz/domena/ucty/news?step=12&amp;page=7">...</a></li>'
    assert parse_pagination(_pager(links))["last_page"] == 1


# --------------------------------------------------------------------------- review follow-ups


def test_campaign_date_ignores_a_distractor_between_label_and_strong():
    html = load("detail_campaign.html").replace(
        'Datum vytvoření: <strong class="kt-font-success">01.11.2026</strong>',
        'Datum vytvoření: (dříve 26.4.51, 03.03.2021) <strong class="kt-font-success">01.11.2026</strong>',
        1,
    )
    assert "03.03.2021" in html
    item = parse_campaign_detail(html, f"{UCTY}/campaign/4695")
    assert item["created_date"] == "2026-11-01"
    assert item["updated_date"] == "2026-11-02"


def test_labeled_date_ignores_a_strong_that_belongs_to_another_label():
    html = load("detail_campaign.html").replace(
        'Datum vytvoření: <strong class="kt-font-success">01.11.2026</strong>',
        'Datum vytvoření: neuvedeno, Datum aktualizace: <strong class="kt-font-success">05.11.2026</strong>',
        1,
    )
    assert "neuvedeno" in html
    item = parse_campaign_detail(html, f"{UCTY}/campaign/4695")
    assert item["created_date"] is None
    assert item["updated_date"] == "2026-11-05"

    # the label may also sit in a separate inline element before the value
    html = load("detail_campaign.html").replace(
        'Datum vytvoření: <strong class="kt-font-success">01.11.2026</strong>',
        'Datum vytvoření: <span>Datum&nbsp;aktualizace:</span> <b>05.11.2026</b>',
        1,
    )
    assert parse_campaign_detail(html, f"{UCTY}/campaign/4695")["created_date"] is None

    # text-only fallback stops at the next label too
    html = load("detail_campaign.html").replace(
        'Datum vytvoření: <strong class="kt-font-success">01.11.2026</strong>',
        "Datum vytvoření: -, Datum aktualizace: 05.11.2026",
        1,
    )
    assert parse_campaign_detail(html, f"{UCTY}/campaign/4695")["created_date"] is None


def test_labeled_date_without_strong_reads_the_text_after_the_label():
    html = load("detail_campaign.html").replace(
        'Datum vytvoření: <strong class="kt-font-success">01.11.2026</strong>',
        "01.01.2020 Datum vytvoření: 01.11.2026",
        1,
    )
    assert parse_campaign_detail(html, f"{UCTY}/campaign/4695")["created_date"] == "2026-11-01"


def test_mystery_worded_date_without_date_element():
    html = load("detail_mystery.html").replace(
        '<p class="ecim-widget-mystery-detail__date">14.10.2026</p>',
        "<p>Aktualizace: 14. října 2026</p>",
        1,
    )
    assert "ecim-widget-mystery-detail__date" not in html
    assert parse_mystery_detail(html, f"{UCTY}/mystery-shopping/496")["date"] == "2026-10-14"


def _subject(content: str) -> str:
    return _page(
        '<div class="ecim-widget-subject-detail">'
        '<h3 class="ecim-widget-subject-detail__title">Banka</h3>'
        f'<div class="ecim-general-content">{content}'
        "<p><strong>Základní informace o společnosti:</strong></p><p>Banka a.s.</p>"
        "</div></div>"
    )


def test_subject_web_link_whose_text_is_the_bank_name():
    html = _subject('<p>Popis banky.</p><p>Web: <a href="https://www.csas.cz">Česká spořitelna</a></p>')
    item = parse_subject_detail(html, f"{UCTY}/subjekt/9")
    assert item["social_links"]["web"] == "https://www.csas.cz"
    assert all(item["social_links"][k] is None for k in ("facebook", "x", "instagram", "linkedin", "youtube"))
    # the links-only paragraph is not part of the description
    assert item["description_text"] == "Popis banky."

    plain = _subject('<p>Popis banky.</p><p><a href="https://www.csas.cz/">Česká spořitelna</a></p>')
    assert parse_subject_detail(plain, f"{UCTY}/subjekt/9")["social_links"]["web"] == "https://www.csas.cz/"


def test_subject_citation_link_in_prose_is_not_the_web():
    html = _subject('<p>Podle údajů <a href="https://www.cnb.cz/">ČNB</a> patří banka mezi největší.</p>')
    item = parse_subject_detail(html, f"{UCTY}/subjekt/9")
    assert item["social_links"]["web"] is None
    assert "ČNB" in item["description_text"]


def test_sanitiser_removes_images_without_a_safe_src():
    html = _page(
        '<div class="ecim-widget-article-detail"><div class="ecim-general-content"><p>Text '
        '<img src="data:image/png;base64,AA"><img src="javascript:x"><img alt="x"></p></div></div>'
    )
    item = parse_news_detail(html, f"{UCTY}/news/9")
    assert "<img" not in item["body_html"]
    assert item["images"] == []


def test_related_portlet_title_with_trailing_colon():
    html = load("detail_company.html").replace("Související zprávy\n", "Související zprávy:\n", 1)
    assert "Související zprávy:" in html
    item = parse_subject_detail(html, f"{UCTY}/subjekt/120")
    assert item["related_ids"]["news"] == [43541, 43539, 43495]
    assert item["related_counts"]["news"] == 3

    counted = load("detail_company.html").replace("Související zprávy\n", "Související zprávy (4075):\n", 1)
    item = parse_subject_detail(counted, f"{UCTY}/subjekt/120")
    assert item["related_ids"]["news"] == [43541, 43539, 43495]
    assert item["related_counts"]["news"] == 4075
