"""Executive-summary list labels before 2020 are "M/YYYY Executive Summary", not Czech month names."""
from src.finecim.parsers import parse_executive_summary_list

URL = "https://www.finecim.cz/cz/domena/ucty/executive-summary"


def _page(entries: str) -> str:
    return f"""<html><body><div id="kt_content"><div id="ecim-summary-list-page">{entries}</div></div></body></html>"""


def _year(year: int, links: str) -> str:
    return (
        f'<div class="row"><div class="col-12"><div class="kt-portlet">'
        f'<div id="ecim-summary-list-page-heading-{year}" class="kt-portlet__head"><h3>{year}</h3></div>'
        f'<div id="ecim-summary-list-page-content-{year}" class="collapse"><div class="kt-portlet__body"><div class="row">'
        f"{links}</div></div></div></div></div></div>"
    )


def _link(sid: int, label: str) -> str:
    return f'<div class="col-12"><div class="kt-portlet"><div class="kt-portlet__body"><a class="h5" href="/cz/domena/ucty/executive-summary/{sid}">{label}</a></div></div></div>'


def test_numeric_labels_before_2020_yield_month_and_year():
    html = _page(
        _year(2026, _link(10664, "červen") + _link(10677, "květen"))
        + _year(2019, _link(4707, "12/2019 Executive Summary") + _link(4650, "11/2019 Executive Summary"))
        + _year(2014, _link(1001, "9/2014 Executive Summary"))
    )
    items = {i["id"]: i for i in parse_executive_summary_list(html, URL)}
    assert items[10664]["year"] == 2026 and items[10664]["month"] == 6
    assert items[4707]["year"] == 2019 and items[4707]["month"] == 12
    assert items[4650]["year"] == 2019 and items[4650]["month"] == 11
    assert items[1001]["year"] == 2014 and items[1001]["month"] == 9
    assert all(i["month"] is not None for i in items.values())


def test_numeric_label_year_overrides_container_year():
    # A month filed under the wrong year container keeps the year printed in its own label.
    html = _page(_year(2019, _link(4600, "1/2020 Executive Summary")))
    (item,) = parse_executive_summary_list(html, URL)
    assert (item["year"], item["month"]) == (2020, 1)


def test_unparseable_label_leaves_month_none():
    html = _page(_year(2018, _link(4000, "Souhrn roku")))
    (item,) = parse_executive_summary_list(html, URL)
    assert item["year"] == 2018 and item["month"] is None
