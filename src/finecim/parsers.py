"""Pure HTML parsers for FINeCIM pages (finecim-research/SCRAPER-DESIGN.md, sections 1.2, 1.3, 3.3).

Every function takes the page HTML (plus the page URL where the id/segment comes from the URL)
and returns plain dicts/lists: ISO dates (``YYYY-MM-DD``), absolute URLs, ``None``/``[]`` for
missing optional fields. :class:`ParseError` is raised only when the page is clearly not the
expected type (the login page, a page without ``#kt_content``, a detail page without its main
widget). No I/O happens here.
"""

from __future__ import annotations

import math
import re
from datetime import date
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

BASE_URL = "https://www.finecim.cz"

__all__ = [
    "BASE_URL",
    "CZECH_MONTHS",
    "ParseError",
    "parse_campaign_creatives",
    "parse_campaign_detail",
    "parse_campaign_list",
    "parse_date_cz",
    "parse_executive_summary_detail",
    "parse_executive_summary_list",
    "parse_item_url",
    "parse_mystery_detail",
    "parse_mystery_list",
    "parse_news_detail",
    "parse_news_list",
    "parse_pagination",
    "parse_product_detail",
    "parse_product_list",
    "parse_product_parameters",
    "parse_subject_detail",
    "parse_subject_list",
]


class ParseError(ValueError):
    """The HTML is not the expected FINeCIM page type (login page, missing content, ...)."""


# Nominative month names as used by the executive-summary pages.
CZECH_MONTHS: dict[str, int] = {
    "leden": 1,
    "únor": 2,
    "březen": 3,
    "duben": 4,
    "květen": 5,
    "červen": 6,
    "červenec": 7,
    "srpen": 8,
    "září": 9,
    "říjen": 10,
    "listopad": 11,
    "prosinec": 12,
}
# Genitive forms ("4. listopadu 2026") seen in free-text source lines.
_CZECH_MONTHS_GENITIVE: dict[str, int] = {
    "ledna": 1,
    "února": 2,
    "března": 3,
    "dubna": 4,
    "května": 5,
    "června": 6,
    "července": 7,
    "srpna": 8,
    "září": 9,
    "října": 10,
    "listopadu": 11,
    "prosince": 12,
}

_ITEM_URL_RE = re.compile(r"/cz/domena/(?P<segment>[^/?#]+)(?:/(?P<entity>[^/?#]+)(?:/(?P<id>\d+))?)?")
_NUMERIC_DATE_RE = re.compile(r"(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})")
_ISO_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_WORD_DATE_RE = re.compile(r"(\d{1,2})\s*\.\s*([^\W\d_]+)\s+(\d{4})")
_WS_RE = re.compile(r"\s+")
# A stand-alone DD.MM.YYYY (also "6. 8. 2026"); never glued to further digits ("26.4.51", "1.2.20260").
_STRICT_DATE_RE = re.compile(r"(?<!\d)(?<!\d\.)(\d{1,2})\.\s?(\d{1,2})\.\s?(\d{4})(?!\d)(?!\.\d)")
# "Label:" prefixes inside date/info blocks ("Datum aktualizace:", "Publikováno:").
_DATE_LABEL_RE = re.compile(r"[^\W\d_]+(?:\s+[^\W\d_]+){0,2}\s*:")
# Trailing item count in a portlet title: "Související zprávy (4075)" / "(4 075)".
_TITLE_COUNT_RE = re.compile(r"\s*\(\s*(\d[\d .]*)\s*\)\s*$")
# URL schemes kept in sanitised href/src ("" = relative).
_SAFE_SCHEMES = frozenset({"", "http", "https", "mailto"})
_URL_CTRL_RE = re.compile(r"[\x00-\x20\x7f]+")

# Body sanitising (spec 3.3).
_ALLOWED_TAGS = frozenset(
    [
        "p",
        "br",
        "strong",
        "b",
        "em",
        "i",
        "u",
        "a",
        "ul",
        "ol",
        "li",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
        "img",
    ]
)
_DROP_TAGS = frozenset(
    [
        "script",
        "style",
        "noscript",
        "iframe",
        "form",
        "input",
        "button",
        "select",
        "textarea",
        "video",
        "audio",
        "source",
        "object",
        "embed",
        "svg",
        "head",
        "title",
        "meta",
        "link",
    ]
)
_ALLOWED_ATTRS: dict[str, frozenset[str]] = {
    "a": frozenset({"href", "title"}),
    "img": frozenset({"src", "alt", "title"}),
    "td": frozenset({"colspan", "rowspan"}),
    "th": frozenset({"colspan", "rowspan"}),
}
_BLOCK_TAGS = frozenset(
    [
        "p",
        "ul",
        "ol",
        "li",
        "blockquote",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "thead",
        "tbody",
        "tr",
        "div",
    ]
)
_BLOCK_TAG_RE = re.compile(
    r"\s*(</?(?:p|ul|ol|li|blockquote|h[1-6]|table|thead|tbody|tr|th|td|br)\b[^>]*>)\s*", re.IGNORECASE
)


# --------------------------------------------------------------------------- small helpers


def _clean(text: str | None) -> str | None:
    """Collapse whitespace (including nbsp) and strip; empty -> None."""
    if text is None:
        return None
    text = _WS_RE.sub(" ", text.replace("\xa0", " ")).strip()
    return text or None


def _text(node: Tag | None) -> str | None:
    return _clean(node.get_text(" ")) if node is not None else None


def _abs(url: str | None) -> str | None:
    if url is None:
        return None
    url = url.strip()
    if not url or url.lower().startswith(("javascript:", "data:", "mailto:", "tel:")):
        return url or None
    return urljoin(BASE_URL + "/", url)


def _safe_url(url: str | None) -> str | None:
    """Absolute http(s)/mailto URL, or None for any other scheme (javascript:, vbscript:, data:, ...)."""
    if url is None:
        return None
    url = url.strip()
    if not url:
        return None
    probe = _URL_CTRL_RE.sub("", url)
    match = re.match(r"^([A-Za-z][A-Za-z0-9+.\-]*):", probe)
    scheme = match.group(1).lower() if match else ""
    if scheme not in _SAFE_SCHEMES:
        return None
    if scheme == "mailto":
        return url
    return _abs(url)


def _strict_date(text: str | None) -> str | None:
    """First stand-alone ``DD.MM.YYYY`` in ``text`` after removing ``Label:`` prefixes (ISO or None)."""
    if not text:
        return None
    text = _DATE_LABEL_RE.sub(" ", str(text).replace("\xa0", " "))
    for match in _STRICT_DATE_RE.finditer(text):
        day, month, year = (int(g) for g in match.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            continue
    return None


def _element_date(node: Tag | None) -> str | None:
    """Date of a dedicated date element: strict DD.MM.YYYY first, then the lenient parser."""
    if node is None:
        return None
    text = _text(node)
    return _strict_date(text) or parse_date_cz(text or "")


def _info_date(info: Tag | None, date_selector: str) -> str | None:
    """Date of an info block: its dedicated date element, else the block text without badges/labels."""
    if info is None:
        return None
    node = info.select_one(date_selector)
    if node is not None:
        return _element_date(node)
    work = BeautifulSoup(str(info), "lxml")
    for noise in work.select("ul, ol, li, [class*=badge], [class*=type]"):
        noise.decompose()
    text = work.get_text(" ")
    return _strict_date(text) or parse_date_cz(_DATE_LABEL_RE.sub(" ", text.replace("\xa0", " ")))


def _canonical(url: str) -> str:
    """Absolute URL without query string and fragment."""
    parts = urlsplit(_abs(url) or "")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _to_int(text: str | None) -> int | None:
    if text is None:
        return None
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def _try_item_url(url: str | None) -> dict | None:
    if not url:
        return None
    match = _ITEM_URL_RE.search(urlsplit(url).path or url)
    if not match:
        return None
    item_id = match.group("id")
    return {
        "segment": match.group("segment"),
        "entity": match.group("entity"),
        "id": int(item_id) if item_id else None,
    }


def _soup(html: str, *, require_content: bool = True) -> BeautifulSoup:
    if html is None or not str(html).strip():
        raise ParseError("empty document")
    soup = BeautifulSoup(html, "lxml")
    if soup.find(id="kt_login_form") is not None:
        raise ParseError("got the FINeCIM sign-in page instead of content (session expired?)")
    if require_content:
        content = soup.find(id="kt_content")
        if content is None:
            raise ParseError("page has no #kt_content")
        if not content.get_text(strip=True) and content.find(True) is None:
            raise ParseError("#kt_content is empty")
    return soup


def _require(soup: BeautifulSoup, selector: str, what: str) -> Tag:
    node = soup.select_one(selector)
    if node is None:
        raise ParseError(f"not a {what} page ({selector} missing)")
    return node


def _badges(root: Tag | None, selector: str) -> list[str]:
    if root is None:
        return []
    return [t for li in root.select(selector) if (t := _text(li))]


def _tags(root: Tag | None, selector: str) -> list[dict]:
    if root is None:
        return []
    out = []
    for a in root.select(selector):
        href = _abs(a.get("href"))
        match = re.search(r"/tags/detail/(\d+)", href or "")
        name = _text(a)
        if not name:
            continue
        out.append({"id": int(match.group(1)) if match else None, "name": name, "url": href})
    return out


def _img_src(node: Tag | None) -> str | None:
    if node is None:
        return None
    return _abs(node.get("src"))


def _split_list(text: str | None) -> list[str]:
    if not text:
        return []
    return [p for part in text.split(",") if (p := _clean(part))]


# Labels of the date lines on campaign/product details; a value element belongs to the
# nearest label before it.
_KNOWN_DATE_LABELS = ("datum vytvoření", "datum aktualizace", "začátek", "konec", "aktualizace")


def _other_labels(label: str) -> list[str]:
    return [o for o in _KNOWN_DATE_LABELS if o != label and o not in label]


def _norm_low(text: str) -> str:
    return _WS_RE.sub(" ", str(text).replace("\xa0", " ")).lower()


def _label_between(start: NavigableString, end: Tag, label: str) -> bool:
    """True when a known date label other than ``label`` occurs after ``label`` in ``start``
    or in any text between ``start`` and ``end``."""
    others = _other_labels(label)
    own = _norm_low(start)
    pos = own.find(label)
    if pos >= 0 and any(o in own[pos + len(label) :] for o in others):
        return True
    node = start.next_element
    while node is not None and node is not end:
        if isinstance(node, NavigableString) and not isinstance(node, Comment):
            text = _norm_low(node)
            if any(o in text for o in others):
                return True
        node = node.next_element
    return False


def _cut_at_label(text: str, label: str) -> str:
    """``text`` up to the first other known date label (the value after ``label`` ends there)."""
    end = len(text)
    for other in _other_labels(label):
        idx = text.find(other)
        if 0 <= idx < end:
            end = idx
    return text[:end]


def _labeled_date(root: Tag | None, selector: str, label: str) -> str | None:
    """Date from a ``<p>Label: <strong>DD.MM.YYYY</strong></p>`` style element.

    The ``<strong>``/``<b>`` following the label is used only when it lies in the same element
    and no other known date label stands between the label and it."""
    if root is None:
        return None
    label = label.lower()
    for p in root.select(selector):
        for string in p.find_all(string=True):
            low = _norm_low(string)
            pos = low.find(label)
            if pos < 0:
                continue
            strong = string.find_next(["strong", "b"])
            if strong is not None and p in strong.parents and not _label_between(string, strong, label):
                # The value element after the label is authoritative; any date-like text
                # between the label and the element is ignored.
                return _element_date(strong)
            found = _strict_date(_cut_at_label(low[pos + len(label) :], label))
            if found:
                return found
            full = (_text(p) or "").lower()
            index = full.find(label)
            if index >= 0:
                found = _strict_date(_cut_at_label(full[index + len(label) :], label))
                if found:
                    return found
    return None


def _categories(root: Tag | None, selector: str) -> dict[str, str | None]:
    """``Produktová linie:`` / ``Segment:`` label -> value pairs."""
    out: dict[str, str | None] = {}
    if root is None:
        return out
    for cat in root.select(selector):
        label = _text(cat.find(["h4", "h5", "strong"]))
        value = _text(cat.find("p"))
        if label:
            out[label.rstrip(":").strip().lower()] = value
    return out


def _item_base(url: str) -> dict:
    info = _try_item_url(url) or {}
    return {"id": info.get("id"), "segment": info.get("segment"), "url": _canonical(url) if url else None}


def _list_segment(url: str) -> str | None:
    info = _try_item_url(url)
    return info["segment"] if info else None


def _card_ref(href: str | None, fallback_segment: str | None) -> dict:
    abs_url = _abs(href)
    info = _try_item_url(abs_url) or {}
    return {
        "id": info.get("id"),
        "segment": info.get("segment") or fallback_segment,
        "url": abs_url,
    }


# --------------------------------------------------------------------------- related widgets


def _norm_title(title: str | None) -> str:
    """Portlet title key: whitespace collapsed, case folded, trailing ``(4075)`` count removed."""
    text = (_clean(title) or "").rstrip(": ")
    return _TITLE_COUNT_RE.sub("", text).strip().rstrip(":").strip().casefold()


def _related_title_counts(soup: BeautifulSoup) -> dict[str, int]:
    """Normalised portlet title -> the count shown in the title (``Související zprávy (4075)``)."""
    out: dict[str, int] = {}
    for widget in soup.select("div.ecim-widget-basic-links"):
        title = (_text(widget.select_one(".kt-portlet__head-title")) or "").rstrip(": ")
        match = _TITLE_COUNT_RE.search(title)
        if match:
            count = _to_int(match.group(1))
            if count is not None:
                key = _norm_title(title)
                out[key] = out.get(key, 0) + count
    return out


def _related_widgets(soup: BeautifulSoup) -> dict[str, list[dict]]:
    """Right-column ``ecim-widget-basic-links`` portlets: normalised title -> [{id, name, url}]."""
    out: dict[str, list[dict]] = {}
    for widget in soup.select("div.ecim-widget-basic-links"):
        title = _norm_title(_text(widget.select_one(".kt-portlet__head-title")))
        items = []
        for a in widget.select(".kt-widget4__item a.kt-widget4__title[href]"):
            href = _abs(a.get("href"))
            if href and "?do=" in href:
                continue
            info = _try_item_url(href) or {}
            items.append({"id": info.get("id"), "name": _text(a), "url": href})
        out.setdefault(title, []).extend(items)
    return out


def _related(widgets: dict[str, list[dict]], title: str) -> list[dict]:
    return list(widgets.get(_norm_title(title), []))


def _attachments(soup: BeautifulSoup) -> list[dict]:
    out = []
    seen: set[str] = set()
    for a in soup.select("div.ecim-widget-attachments .kt-widget4__item a.pdf-media-desktop[href]"):
        url = _abs(a.get("href"))
        if not url or url in seen:
            continue
        seen.add(url)
        out.append({"name": _text(a), "url": url})
    return out


# --------------------------------------------------------------------------- sanitising


def _sanitize_tree(node: Tag) -> None:
    for child in list(node.children):
        if isinstance(child, Comment):
            child.extract()
        elif isinstance(child, NavigableString):
            continue
        elif isinstance(child, Tag):
            name = (child.name or "").lower()
            if name in _DROP_TAGS:
                child.decompose()
                continue
            _sanitize_tree(child)
            if name not in _ALLOWED_TAGS:
                child.unwrap()
                continue
            allowed = _ALLOWED_ATTRS.get(name, frozenset())
            attrs = {}
            for key, value in child.attrs.items():
                if key.lower() not in allowed:
                    continue
                if isinstance(value, list):
                    value = " ".join(value)
                if key.lower() in ("href", "src"):
                    value = _safe_url(value)
                    if not value:
                        continue
                attrs[key.lower()] = value
            if name == "img" and "src" not in attrs:
                child.decompose()
                continue
            child.attrs = attrs


def _sanitized_soup(nodes) -> Tag:
    """Re-parse the given nodes into a fresh, sanitised ``<body>``."""
    markup = "".join(str(n) for n in nodes)
    work = BeautifulSoup(f"<html><body>{markup}</body></html>", "lxml")
    body = work.body
    if body is None:  # pragma: no cover - lxml always creates a body
        body = work
    # Whitespace-only inline tags become one space (deleting them would join the words around them).
    for tag in body.find_all(["strong", "b", "em", "i", "u", "span"]):
        if tag.parent is None or tag.find("img") is not None or tag.get_text(strip=True):
            continue
        if tag.find("br") is not None:
            tag.unwrap()
        elif tag.get_text(""):
            tag.replace_with(NavigableString(" "))
        else:
            tag.decompose()
    _sanitize_tree(body)
    # Drop paragraphs / list items that carry neither text nor an image.
    for tag in body.find_all(["p", "li", "blockquote"]):
        if tag.parent is None:
            continue
        if not tag.get_text(strip=True).replace("\xa0", "") and tag.find("img") is None:
            tag.decompose()
    return body


def _sanitized_html(body: Tag) -> str:
    html = "".join(str(c) for c in body.contents)
    html = _WS_RE.sub(" ", html.replace("\xa0", " "))
    html = _BLOCK_TAG_RE.sub(r"\1", html)
    return html.strip()


def _body_text(body: Tag) -> str:
    """Plain text of a sanitised body, paragraphs separated by blank lines."""
    work = BeautifulSoup(str(body), "lxml")
    for br in work.find_all("br"):
        br.replace_with(NavigableString("\n"))
    for tag in work.find_all(list(_BLOCK_TAGS)):
        tag.insert_before(NavigableString("\n\n"))
        tag.insert_after(NavigableString("\n\n"))
    for cell in work.find_all(["td", "th"]):
        cell.insert_after(NavigableString(" "))
    raw = work.get_text("")
    paragraphs = []
    for chunk in re.split(r"\n[ \t\xa0]*\n", raw):
        lines = [_clean(line) for line in chunk.split("\n")]
        lines = [line for line in lines if line]
        if lines:
            paragraphs.append("\n".join(lines))
    return "\n\n".join(paragraphs)


def _sanitize(nodes) -> tuple[str, str, list[str]]:
    """(body_html, body_text, image urls) for a list of nodes."""
    body = _sanitized_soup(nodes)
    images = [src for img in body.find_all("img") if (src := img.get("src"))]
    return _sanitized_html(body), _body_text(body), images


def _content_children(container: Tag | None, *, exclude: Tag | None = None) -> list:
    if container is None:
        return []
    return [c for c in container.children if c is not exclude and not isinstance(c, Comment)]


# --------------------------------------------------------------------------- generic


def parse_item_url(url: str) -> dict:
    """``…/cz/domena/<segment>/<entity>/<id>`` -> ``{"segment", "entity", "id"}``.

    ``entity`` is the raw path component (``news``, ``campaign``, ``mystery-shopping``,
    ``produkt``, ``subjekt``, ``executive-summary``; list URLs give ``id`` None).
    Raises ParseError when the URL is not under ``/cz/domena/``.
    """
    info = _try_item_url(url)
    if info is None:
        raise ParseError(f"not a FINeCIM domain URL: {url!r}")
    return info


def parse_date_cz(text: str) -> str | None:
    """``05.11.2026`` / ``6. 8. 2026`` / ``4. listopadu 2026`` -> ``2026-11-05`` (None if not a date)."""
    if not text:
        return None
    text = str(text).replace("\xa0", " ")
    match = _NUMERIC_DATE_RE.search(text)
    if match:
        day, month, year = (int(g) for g in match.groups())
    else:
        match = _ISO_DATE_RE.search(text)
        if match:
            year, month, day = (int(g) for g in match.groups())
        else:
            match = _WORD_DATE_RE.search(text)
            if not match:
                return None
            word = match.group(2).lower()
            month = CZECH_MONTHS.get(word) or _CZECH_MONTHS_GENITIVE.get(word) or 0
            day, year = int(match.group(1)), int(match.group(3))
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_pagination(html: str) -> dict:
    """Footer of a list page -> ``{"total", "step", "page", "last_page"}``.

    ``total``/``step`` are None when the page has no footer; ``page``/``last_page`` default to 1.
    """
    soup = _soup(html, require_content=False)
    total = step = None
    first_shown = last_shown = None
    info = soup.select_one(".m-datatable__pager-detail")
    info_text = _text(info) if info else None
    if info_text is None:
        node = soup.find(string=re.compile(r"Zobrazeno"))
        info_text = _clean(str(node)) if node else None
    if info_text:
        match = re.search(r"(\d[\d ]*)\s*-\s*(\d[\d ]*)\s*z\s*(\d[\d ]*)", info_text)
        if match:
            first_shown, last_shown, total = (_to_int(g) for g in match.groups())

    pager = soup.select_one(".kt-pagination")
    if pager is not None:
        selected = pager.select_one(".m-datatable__pager-size .filter-option") or pager.select_one(
            "li.selected .text"
        )
        step = _to_int(_text(selected)) if selected else None

    def _qs_int(href: str | None, key: str) -> int | None:
        if not href:
            return None
        values = parse_qs(urlsplit(href).query).get(key)
        return _to_int(values[0]) if values else None

    active = pager.select_one("a.kt-pagination__link--active") if pager is not None else None
    page = None
    if active is not None:
        page = _qs_int(active.get("href"), "page") or _to_int(_text(active)) or 1
        if step is None:
            step = _qs_int(active.get("href"), "step")
    if step is None and first_shown and last_shown and last_shown >= first_shown:
        step = last_shown - first_shown + 1 if total is None or last_shown < total else None
    page = page or 1

    last_page = None
    has_size_select = False
    numbered: list[int] = []
    if pager is not None:
        last_link = pager.select_one("li.kt-pagination__link--last a[href]")
        if last_link is not None:
            last_page = _qs_int(last_link.get("href"), "page")
        has_size_select = pager.select_one(".m-datatable__pager-size") is not None
        for a in pager.select("ul.kt-pagination__links a"):
            label = _text(a) or ""
            if re.fullmatch(r"\d+", label):
                numbered.append(_qs_int(a.get("href"), "page") or int(label))
    from_total = max(1, math.ceil(total / step)) if total is not None and step else None
    if last_page is None and has_size_select and from_total is not None:
        last_page = from_total
    if last_page is None:
        # No last-page anchor and no page-size select: the highest numbered page link, else
        # total/step from the footer, else 1 (in this order, as the spec says).
        last_page = max(numbered) if numbered else from_total
    last_page = max(last_page or page, page)
    return {"total": total, "step": step, "page": page, "last_page": last_page}


# --------------------------------------------------------------------------- list pages


def _listing_container(soup: BeautifulSoup, container_selector: str) -> Tag:
    """The listing container of a list page; ParseError when ``#kt_content`` lacks it.

    An existing container without cards is a valid empty page (the caller returns ``[]``)."""
    container = soup.select_one(container_selector)
    if container is None:
        raise ParseError("listing container missing")
    return container


def _cards(soup: BeautifulSoup, container_selector: str, card_selector: str) -> list[Tag]:
    return _listing_container(soup, container_selector).select(card_selector)


def parse_news_list(html: str, url: str) -> list[dict]:
    soup = _soup(html)
    segment = _list_segment(url)
    out = []
    for card in _cards(soup, "#snippet--listingItems", ".ecim-widget-article"):
        link = card.select_one("h3.ecim-widget-article__title a[href]")
        if link is None:
            continue
        item = _card_ref(link.get("href"), segment)
        item.update(
            {
                "title": _text(link),
                "date": parse_date_cz(_text(card.select_one("p.ecim-widget-article__date")) or ""),
                "badges": _badges(card, "ul.ecim-widget-article__badges li"),
                "annotation": _text(card.select_one("p.ecim-widget-article__body___annotation")),
                "tags": _tags(card, "ul.ecim-widget-article__tags a[href]"),
                "logo_url": _img_src(card.select_one("img.ecim-widget-article__img")),
            }
        )
        out.append(item)
    return out


def parse_campaign_list(html: str, url: str) -> list[dict]:
    soup = _soup(html)
    segment = _list_segment(url)
    out = []
    for card in _cards(soup, "#snippet--listing", ".ecim-widget-campaign"):
        link = card.select_one("h3.ecim-widget-campaign__title a[href]")
        if link is None:
            continue
        start_date = updated_date = None
        for p in card.select("p.ecim-widget-campaign__date"):
            text = (_text(p) or "").lower()
            if text.startswith("začátek"):
                start_date = parse_date_cz(text)
            elif text.startswith("aktualizace"):
                updated_date = parse_date_cz(text)
        media_types = []
        for button in card.select("ul.ecim-widget-campaign__btns button"):
            label = _clean(button.get("data-title")) or _text(button)
            if label and label not in media_types:
                media_types.append(label)
        thumb = card.select_one("a.ecim-widget-campaign__main-image img") or card.select_one(
            "img.ecim-widget-campaign__main-img"
        )
        item = _card_ref(link.get("href"), segment)
        item.update(
            {
                "title": _text(link),
                "start_date": start_date,
                "updated_date": updated_date,
                "badges": _badges(card, "ul.ecim-widget-campaign__badges li"),
                "annotation": _text(card.select_one("p.ecim-widget-campaign__body___annotation")),
                "media_types": media_types,
                "thumbnail_url": _img_src(thumb),
            }
        )
        out.append(item)
    return out


def parse_mystery_list(html: str, url: str) -> list[dict]:
    soup = _soup(html)
    segment = _list_segment(url)
    out = []
    for card in _cards(soup, "#snippet--listingItems", ".ecim-widget-general"):
        link = card.select_one("h3.kt-portlet__head-title a[href]")
        if link is None:
            continue
        date_node = card.select_one(".kt-portlet__body > p > strong")
        item = _card_ref(link.get("href"), segment)
        item.update(
            {
                "title": _text(link),
                "date": parse_date_cz(_text(date_node) or ""),
                "annotation": _text(card.select_one("p.ecim-widget-mystery__body___annotation")),
            }
        )
        out.append(item)
    return out


def parse_product_list(html: str, url: str) -> list[dict]:
    soup = _soup(html)
    segment = _list_segment(url)
    out = []
    for card in _cards(soup, "#snippet--listing", ".ecim-widget-product"):
        link = card.select_one("h3.ecim-widget-product__title a[href]")
        if link is None:
            continue
        cats = _categories(card, ".ecim-widget-product__category")
        item = _card_ref(link.get("href"), segment)
        item.update(
            {
                "title": _text(link),
                "product_line": cats.get("produktová linie"),
                "customer_segment": cats.get("segment"),
                "annotation": _text(card.select_one("p.ecim-widget-product__body___annotation")),
                "badges": _badges(card, "ul.ecim-widget-product__badges li"),
                "logo_url": _img_src(card.select_one("img.ecim-widget-product__img")),
            }
        )
        out.append(item)
    return out


def parse_subject_list(html: str, url: str) -> list[dict]:
    soup = _soup(html)
    segment = _list_segment(url)
    _listing_container(soup, "#snippet--content .row")
    container = soup.select_one("#snippet--content")
    out = []
    seen: set[int] = set()
    for card in container.select(".ecim-widget-subject"):
        link = card.select_one("a.ecim-widget-subject__link[href]")
        if link is None:
            continue
        item = _card_ref(link.get("href"), segment)
        if item["id"] is not None:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
        img = link.find("img")
        name = (
            _text(link.find("span"))
            or _text(link.select_one(".ecim-widget-subject__title"))
            or (_clean(img.get("alt")) if img is not None else None)
        )
        item.update({"name": name, "logo_url": _img_src(img)})
        out.append(item)
    return out


# --------------------------------------------------------------------------- detail pages


def _news_date(widget: Tag, info: Tag | None) -> str | None:
    node = widget.select_one(".ecim-widget-article-detail__date")
    if node is not None:
        return _element_date(node)
    return _info_date(info, ".ecim-widget-article-detail__date")


def parse_news_detail(html: str, url: str) -> dict:
    soup = _soup(html)
    widget = _require(soup, ".ecim-widget-article-detail", "news detail")
    info = widget.select_one(".ecim-widget-article-detail__info")
    content = widget.select_one("div.ecim-general-content")
    perex_node = content.select_one("p.news-annotation-text") if content is not None else None
    body_html, body_text, images = _sanitize(_content_children(content, exclude=perex_node))

    source_line = None
    if content is not None:
        for p in content.find_all("p"):
            text = _text(p)
            if text and text.lower().startswith("zdroj"):
                source_line = text
    news_type = widget.select_one(".ecim-widget-article-detail__news-type span")
    widgets = _related_widgets(soup)
    out = _item_base(url)
    out.update(
        {
            "title": _text(widget.select_one("h3.ecim-widget-article-detail__title")),
            "date": _news_date(widget, info),
            "badges": _badges(info, "ul.ecim-widget-article-detail__badges li"),
            "news_types": _split_list(_text(news_type)),
            "perex": _text(perex_node),
            "body_html": body_html or None,
            "body_text": body_text or None,
            "tags": _tags(widget, "ul.ecim-widget-article-detail__tags a[href]"),
            "images": images,
            "source_line": source_line,
            "related_subjects": _related(widgets, "Související společnosti"),
            "related_products": _related(widgets, "Související produkty"),
            "related_news": _related(widgets, "Související zprávy"),
        }
    )
    return out


def parse_campaign_detail(html: str, url: str) -> dict:
    soup = _soup(html)
    widget = _require(soup, ".ecim-widget-campaign-detail", "campaign detail")
    dates_sel = ".ecim-widget-campaign-detail__dates p"
    campaign_type = widget.select_one(".ecim-widget-campaign-detail__campaign-type span")

    annotation_node = widget.select_one("div.campaign-annotation-text")
    annotation = None
    if annotation_node is not None:
        paragraphs = [t for p in annotation_node.find_all("p") if (t := _text(p))]
        annotation = "\n\n".join(paragraphs) if paragraphs else _text(annotation_node)

    media = []
    for button in widget.select(
        "ul.ecim-widget-campaing-detail__btns button, ul.ecim-widget-campaign-detail__btns button"
    ):
        count_node = button.select_one(".count")
        count = _to_int(_text(count_node)) if count_node is not None else None
        if count is None:
            match = re.search(r"\d+", button.get_text(" "))
            count = int(match.group(0)) if match else None
        media_type = _clean(button.get("data-title"))
        if media_type is None:
            raw = _text(button) or ""
            media_type = _clean(re.sub(r"\d+", "", raw))
        media.append({"type": media_type, "count": count, "creatives_url": _abs(button.get("data-load"))})

    timeline = []
    for event in soup.select(".ecim-widget-campaign-timeline .ecim-widget-campaign-timeline-event"):
        content = event.select_one(".kt-timeline-v1__item-content") or event
        paragraphs = [t for p in content.find_all("p", recursive=False) if (t := _text(p))]
        timeline.append(
            {
                "date": parse_date_cz(_text(event.select_one(".kt-timeline-v1__item-time")) or ""),
                "text": "\n\n".join(paragraphs) or None,
            }
        )

    widgets = _related_widgets(soup)
    out = _item_base(url)
    out.update(
        {
            "title": _text(widget.select_one("h3.ecim-widget-campaign-detail__title")),
            "created_date": _labeled_date(widget, dates_sel, "Datum vytvoření"),
            "updated_date": _labeled_date(widget, dates_sel, "Datum aktualizace"),
            "badges": _badges(widget, "ul.ecim-widget-campaign-detail__badges li"),
            "campaign_types": _split_list(_text(campaign_type)),
            "annotation": annotation,
            "key_visual_url": _img_src(widget.select_one("div.campaign-annotation-img img")),
            "media": media,
            "timeline": timeline,
            "related_subjects": _related(widgets, "Související společnosti"),
            "related_products": _related(widgets, "Související produkty"),
            "related_campaigns": _related(widgets, "Související kampaně"),
        }
    )
    return out


def parse_campaign_creatives(html: str, campaign_url: str) -> list[dict]:
    """The AJAX fragment behind a campaign media button (``?do=campaignCreatives``).

    An empty / whitespace-only fragment or one without events gives ``[]``; the sign-in page
    still raises :class:`ParseError`.
    """
    if html is None or not str(html).strip():
        return []
    soup = _soup(html, require_content=False)
    out = []
    for event in soup.select("div.ecim-widget-campaign-event"):
        creative_id = None
        copy = event.select_one("[data-copy]")
        if copy is not None:
            values = parse_qs(urlsplit(copy.get("data-copy", "")).query).get("creativeId")
            creative_id = _to_int(values[0]) if values else None
        body = event.select_one("div.ecim-general-content") or event.select_one(".kt-portlet__body")
        media_url = media_kind = None
        text = None
        if body is not None:
            video = body.find("video")
            if video is not None:
                source = video.find("source", src=True)
                media_url = _abs(source.get("src") if source is not None else video.get("src"))
                media_kind = "video" if media_url else None
            if media_url is None:
                img = body.find("img", src=True)
                if img is not None:
                    media_url, media_kind = _abs(img.get("src")), "image"
            _, body_text, _ = _sanitize(list(body.children))
            text = body_text or None
        out.append(
            {
                "creative_id": creative_id,
                "date": parse_date_cz(_text(event.select_one("h3.kt-portlet__head-title")) or ""),
                "text": text,
                "media_url": media_url,
                "media_kind": media_kind,
            }
        )
    return out


def _mystery_date(widget: Tag) -> str | None:
    info = widget.select_one(".ecim-widget-mystery-detail__info")
    if info is not None:
        return _info_date(info, ".ecim-widget-mystery-detail__date")
    return _element_date(widget.select_one(".ecim-widget-mystery-detail__date"))


def parse_mystery_detail(html: str, url: str) -> dict:
    """Mystery-shopping detail. Adds ``body_text`` (not in the spec key list) for ``popis``."""
    soup = _soup(html)
    widget = _require(soup, ".ecim-widget-mystery-detail", "mystery-shopping detail")
    content = widget.select_one("div.ecim-general-content")
    perex_node = content.select_one("p.ms-annotation-text") if content is not None else None
    body_html, body_text, _ = _sanitize(_content_children(content, exclude=perex_node))
    attachments = _attachments(soup)

    pdf_url = None
    if content is not None:
        link = content.select_one('a[href*="/media/pdf/open"]') or content.select_one(
            'a[href*="/media/pdf/"]'
        )
        if link is not None:
            pdf_url = _abs(link.get("href"))
    if pdf_url is None and attachments:
        pdf_url = attachments[0]["url"]

    widgets = _related_widgets(soup)
    out = _item_base(url)
    out.update(
        {
            "title": _text(widget.select_one("h3.ecim-widget-mystery-detail__title")),
            "date": _mystery_date(widget),
            "perex": _text(perex_node),
            "body_html": body_html or None,
            "body_text": body_text or None,
            "pdf_url": pdf_url,
            "attachments": attachments,
            "tags": _tags(widget, "ul.ecim-widget-mystery-detail__tags a[href]"),
            "related_subjects": _related(widgets, "Související společnosti"),
            "related_products": _related(widgets, "Související produkty"),
        }
    )
    return out


def parse_product_detail(html: str, url: str) -> dict:
    soup = _soup(html)
    widget = _require(soup, ".ecim-widget-product-detail", "product detail")
    dates_sel = ".ecim-widget-product-detail__dates p, .ecim-widget-product-detail__info p"
    cats = _categories(widget, ".ecim-widget-product-detail__category")
    base = _item_base(url)

    def _link(fragment: str) -> str | None:
        node = soup.select_one(f'a[href*="/produkty/{fragment}/"]')
        if node is not None:
            return _abs(node.get("href"))
        if base["segment"] and base["id"] is not None:
            return f"{BASE_URL}/cz/domena/{base['segment']}/produkty/{fragment}/{base['id']}"
        return None

    widgets = _related_widgets(soup)
    base.update(
        {
            "title": _text(widget.select_one("h3.ecim-widget-product-detail__title")),
            "created_date": _labeled_date(widget, dates_sel, "Datum vytvoření"),
            "updated_date": _labeled_date(widget, dates_sel, "Datum aktualizace"),
            "product_line": cats.get("produktová linie"),
            "customer_segment": cats.get("segment"),
            "annotation": _text(widget.select_one("p.product-annotation-text")),
            "logo_url": _img_src(widget.select_one("img.ecim-widget-product-detail__img")),
            "parameters_url": _link("parameters-new-window"),
            "history_url": _link("history-new-window"),
            "related_subjects": _related(widgets, "Související společnosti"),
            "related_news": _related(widgets, "Související zprávy"),
        }
    )
    return base


def parse_product_parameters(html: str) -> list[dict]:
    """Parameters accordion (standalone ``parameters-new-window`` page or the product detail)."""
    soup = _soup(html)
    cards = soup.select("#accordion .card") or soup.select(".accordion .card")
    out = []
    for card in cards:
        section = _text(card.select_one(".card-header"))
        for row in card.select(".card-body tr"):
            th = row.find("th")
            cells = row.find_all("td")
            if th is None and len(cells) >= 2:
                name, value = _text(cells[0]), _text(cells[1])
            else:
                name, value = _text(th), _text(cells[0]) if cells else None
            if name is None and value is None:
                continue
            out.append({"section": section, "name": name, "value": value})
    return out


# --------------------------------------------------------------------------- company profile

_SOCIAL_HOSTS = (
    ("facebook", ("facebook.com", "fb.com", "fb.me")),
    ("instagram", ("instagram.com",)),
    ("x", ("x.com", "twitter.com")),
    ("linkedin", ("linkedin.com",)),
    ("youtube", ("youtube.com", "youtu.be")),
)
_INFO_LABELS = (
    ("legal_name", ("obchodní firma",)),
    ("ico", ("identifikační číslo", "ičo", "ič")),
    ("address", ("sídlo",)),
    ("share_capital", ("základní kapitál",)),
    ("shareholder", ("akcionář", "akcionáři", "jediný akcionář")),
    ("board", ("představenstvo",)),
)
# The number immediately preceding a KPI keyword: "4 600 000 klientů", "200 000+ klientů",
# "4,6 mil. klientů", "4.600.000 klientů". The look-behind keeps a preceding year ("2025 200 000")
# from being glued onto the number.
_NUM = (
    r"(?<![\d.,])(\d{1,3}(?:[ \xa0\u202f]\d{3})+|\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+)|\.(\d{1,2})(?!\d))?"
    r"\s*(mil\.?|milion\w*|tis\.?|tisíc\w*)?\s*\+?\s*"
)
_KPI_KEYWORDS = {"clients": "klient", "branches": "pobo", "atms": "bankomat"}
_KPI_PATTERNS = {key: re.compile(_NUM + word, re.IGNORECASE) for key, word in _KPI_KEYWORDS.items()}


def _social_key(href: str) -> str | None:
    host = (urlsplit(href).hostname or "").lower()
    if not host:
        return None
    for key, hosts in _SOCIAL_HOSTS:
        if any(host == h or host.endswith("." + h) for h in hosts):
            return key
    if host.endswith("finecim.cz"):
        return None
    return "web"


def _is_external_http(href: str | None) -> bool:
    if not href:
        return False
    parts = urlsplit(href)
    host = (parts.hostname or "").lower()
    return parts.scheme in ("http", "https") and bool(host) and not host.endswith("finecim.cz")


# Leading label of a links paragraph ("Web:", "Sledujte nás:", "Najdete nás na:").
_LINK_LEAD_RE = re.compile(
    r"^\s*(?:web(?:ové stránky)?|www|internet(?:ové stránky)?|sledujte(?: nás)?(?: na)?|"
    r"najdete nás(?: na)?|odkazy|kontakt)\s*:?",
    re.IGNORECASE,
)
# Characters of non-link text a paragraph may carry and still count as a links paragraph.
_LINK_PARAGRAPH_SLACK = 12


def _block_social_links(block: Tag) -> tuple[dict[str, str], bool]:
    """Social/web links of one description paragraph -> ({key: url}, paragraph is only links).

    Icon links (image or empty anchors) map any external host; text links map the social hosts,
    plus the bank's own site when it is the only external non-social http(s) link in the paragraph.
    """
    found: dict[str, str] = {}
    anchors = [(a, _safe_url(a.get("href"))) for a in block.find_all("a", href=True)]
    external = [(a, href) for a, href in anchors if _is_external_http(href)]
    non_social = [(a, href) for a, href in external if _social_key(href) == "web"]
    # Text outside the anchors, without separators and a leading "Web:" / "Sledujte nás:" label.
    all_text = _text(block) or ""
    anchor_text = "".join(_text(a) or "" for a, _ in anchors)
    block_text = _LINK_LEAD_RE.sub("", all_text, count=1)
    block_text = re.sub(r"[\s|,;/·•–:-]+", "", block_text)
    other_text = len(block_text) - len(re.sub(r"[\s|,;/·•–:-]+", "", anchor_text))
    # A citation link inside prose is not the bank's site; a short link paragraph is.
    is_link_paragraph = other_text <= _LINK_PARAGRAPH_SLACK or _LINK_LEAD_RE.match(all_text) is not None
    linked_text = 0
    for a, href in external:
        key = _social_key(href)
        if key is None:
            continue
        is_icon = a.find("img") is not None or not _text(a)
        if key == "web" and not is_icon and (len(non_social) != 1 or not is_link_paragraph):
            continue
        found.setdefault(key, href)
        linked_text += len(re.sub(r"[\s|,;/·•–:-]+", "", _text(a) or ""))
    only_links = bool(found) and len(block_text) <= linked_text
    return found, only_links


def _kpi(text: str, key: str) -> int | None:
    """The number directly in front of the KPI keyword (``klient``/``pobo``/``bankomat``)."""
    match = _KPI_PATTERNS[key].search(text)
    if not match:
        return None
    whole = int(re.sub(r"\D", "", match.group(1)))
    fraction = match.group(2) or match.group(3)
    unit = (match.group(4) or "").lower()
    if unit:
        multiplier = 1_000_000 if unit.startswith("mil") else 1_000
        value = float(f"{whole}.{fraction}") if fraction else float(whole)
        return int(round(value * multiplier))
    return whole


_LABEL_RE = re.compile(r"^\s*([^:\n]{2,60}?)\s*:\s*(.*)$", re.DOTALL)


def _label_pairs(paragraph: Tag) -> list[tuple[str, str]]:
    """``<strong>Label:</strong> value<br>…`` -> [(label, raw value with newlines)].

    Walks all descendants (labels may sit inside ``<span>`` wrappers); a ``<strong>Label</strong>``
    whose colon follows outside the tag (``<strong>Sídlo</strong>: …``) is a label too.
    """
    pairs: list[list[str]] = []
    pending: list[str] = []  # a bold text without colon that may be a label

    def add_text(text: str) -> None:
        text = text.replace("\xa0", " ")
        if pending:
            label = pending.pop()
            match = re.match(r"^\s*:\s*(.*)$", text, re.DOTALL)
            if match and _info_key(label) is not None:
                pairs.append([label, match.group(1)])
                return
            if pairs:
                pairs[-1][1] += label
        if pairs:
            pairs[-1][1] += text

    def walk(node: Tag) -> None:
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                add_text(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            if child.name in ("strong", "b"):
                text = child.get_text("").replace("\xa0", " ")
                match = _LABEL_RE.match(text)
                if match:
                    if pending:
                        add_text("")
                    pairs.append([match.group(1), match.group(2)])
                elif text.strip() and _info_key(text) is not None:
                    if pending:
                        add_text("")
                    pending.append(text.strip())
                else:
                    add_text(text)
                continue
            if child.name == "br":
                add_text("\n")
                continue
            if child.name in ("p", "div", "li"):
                add_text("\n")
                walk(child)
                add_text("\n")
                continue
            walk(child)

    walk(paragraph)
    if pending:
        add_text("")
    return [(label, value) for label, value in pairs]


def _info_key(label: str) -> str | None:
    label = (_clean(label) or "").lower()
    for key, prefixes in _INFO_LABELS:
        if any(label == p or label.startswith(p + " ") for p in prefixes):
            return key
    return None


_MEMBER_RE = re.compile(r"([^()]*?)\s*\(([^()]*)\)\s*[,;]?")
_RUN_RE = re.compile(r"\s{2,}|\s*;\s*")


def _board(value: str) -> list[dict]:
    """Board members ``Name (role)`` separated by ``<br>`` (newlines) and/or runs of nbsp."""
    members: list[dict] = []

    def plain(chunk: str) -> None:
        for name in _RUN_RE.split(chunk.replace("\xa0", " ")):
            name = (_clean(name) or "").strip(",; ")
            if name:
                members.append({"name": name, "role": None})

    for line in value.replace("\xa0", " ").split("\n"):
        if not line.strip():
            continue
        pos = 0
        for match in _MEMBER_RE.finditer(line):
            if not match.group(0).strip():
                continue
            parts = [p for p in _RUN_RE.split(match.group(1).strip()) if p.strip()]
            for extra in parts[:-1]:
                plain(extra)
            name = (_clean(parts[-1]) if parts else None) or ""
            name = name.strip(",; ")
            role = _clean(match.group(2))
            if name:
                members.append({"name": name, "role": role})
            pos = match.end()
        plain(line[pos:])
    return members


def parse_subject_detail(html: str, url: str) -> dict:
    soup = _soup(html)
    widget = _require(soup, ".ecim-widget-subject-detail", "company detail")
    content = widget.select_one("div.ecim-general-content")
    blocks = [c for c in _content_children(content) if isinstance(c, Tag)]

    info_index = len(blocks)
    for index, block in enumerate(blocks):
        if "základní informace" in (block.get_text(" ") or "").lower():
            info_index = index
            break

    social_links: dict[str, str | None] = {
        k: None for k in ("facebook", "x", "instagram", "linkedin", "youtube")
    }
    social_links["web"] = None
    description_blocks = []
    for block in blocks[:info_index]:
        links, only_links = _block_social_links(block)
        for key, href in links.items():
            if social_links.get(key) is None:
                social_links[key] = href
        if _text(block) is None or only_links:
            continue
        description_blocks.append(block)
    description_html, description_text, _ = _sanitize(description_blocks)

    fields: dict[str, object] = {}
    info_text_parts = []
    for block in blocks[info_index:]:
        info_text_parts.append(block.get_text(" "))
        paragraphs = [block] if block.name == "p" else block.find_all("p") or [block]
        for paragraph in paragraphs:
            for label, value in _label_pairs(paragraph):
                key = _info_key(label)
                if key is None or key in fields:
                    continue
                if key == "board":
                    fields[key] = _board(value)
                elif key == "ico":
                    digits = re.sub(r"\D", "", value)
                    fields[key] = digits or None
                else:
                    fields[key] = _clean(value)
    info_text = _clean(" ".join(info_text_parts)) or ""

    widgets = _related_widgets(soup)
    title_counts = _related_title_counts(soup)
    related_titles = {
        "news": "Související zprávy",
        "campaigns": "Související kampaně",
        "mystery": "Související Mystery Shopping",
        "products": "Související produkty",
    }
    related_ids = {
        "news": [i["id"] for i in _related(widgets, "Související zprávy") if i["id"] is not None],
        "campaigns": [i["id"] for i in _related(widgets, "Související kampaně") if i["id"] is not None],
        "mystery": [
            i["id"] for i in _related(widgets, "Související Mystery Shopping") if i["id"] is not None
        ],
        "products": [i["id"] for i in _related(widgets, "Související produkty") if i["id"] is not None],
    }
    date_node = widget.select_one(".ecim-widget-subject-detail__date strong") or widget.select_one(
        ".ecim-widget-subject-detail__date"
    )
    out = _item_base(url)
    out.update(
        {
            "name": _text(widget.select_one("h3.ecim-widget-subject-detail__title")),
            "updated_date": parse_date_cz(_text(date_node) or ""),
            "logo_url": _img_src(widget.select_one("img.ecim-widget-subject-detail__img")),
            "description_text": description_text or None,
            "description_html": description_html or None,
            "social_links": social_links,
            "legal_name": fields.get("legal_name"),
            "ico": fields.get("ico"),
            "address": fields.get("address"),
            "share_capital": fields.get("share_capital"),
            "shareholder": fields.get("shareholder"),
            "board": fields.get("board") or [],
            "clients": _kpi(info_text, "clients"),
            "branches": _kpi(info_text, "branches"),
            "atms": _kpi(info_text, "atms"),
            "attachments": _attachments(soup),
            "related_counts": {
                key: max(title_counts.get(_norm_title(related_titles[key]), 0), len(ids))
                for key, ids in related_ids.items()
            },
            "related_ids": related_ids,
        }
    )
    return out


# --------------------------------------------------------------------------- executive summary


def parse_executive_summary_list(html: str, url: str) -> list[dict]:
    soup = _soup(html)
    segment = _list_segment(url)
    out = []
    seen: set[int] = set()
    for heading in soup.select('[id^="ecim-summary-list-page-heading-"]'):
        match = re.search(r"(\d{4})$", heading.get("id", ""))
        if not match:
            continue
        year = int(match.group(1))
        content = soup.find(id=f"ecim-summary-list-page-content-{year}")
        if content is None:
            content = heading.parent
        for a in content.select("a.h5[href]") or content.select('a[href*="/executive-summary/"]'):
            item = _card_ref(a.get("href"), segment)
            if item["id"] is None or item["id"] in seen:
                continue
            seen.add(item["id"])
            month_name = _text(a)
            month = CZECH_MONTHS.get((month_name or "").lower())
            if month is None:
                # Months before 2020 are labelled "12/2019 Executive Summary" instead of a Czech name.
                numeric = re.match(r"^\s*(\d{1,2})\s*/\s*(\d{4})(?!\d)", month_name or "")
                if numeric and 1 <= int(numeric.group(1)) <= 12:
                    month = int(numeric.group(1))
                    year = int(numeric.group(2))
            item.update(
                {
                    "year": year,
                    "month": month,
                    "month_name": month_name,
                }
            )
            out.append(item)
    return out


#: Item types an executive-summary entry can link to (the URL's entity segment).
_SUMMARY_ENTITIES = frozenset({"news", "campaign", "mystery-shopping", "produkt"})


def parse_executive_summary_detail(html: str, url: str) -> dict:
    """Month page of the executive summary.

    Each entry has ``entity`` (``news`` / ``campaign`` / ``mystery-shopping`` / ``produkt``, or
    None for any other link) and ``item_url`` (absolute URL of the linked item). ``news_id`` is
    set only for news entries; ``news_url`` repeats ``item_url`` for backward compatibility."""
    soup = _soup(html)
    page = soup.select_one(".ecim-summary-page")
    title = soup.select_one("h1.ecim-summary-page__title")
    if page is None and title is None:
        raise ParseError("not an executive-summary month page (.ecim-summary-page missing)")
    root = page or soup
    entries = []
    for entry in root.select("div.ecim-widget-summary"):
        link = entry.select_one("h3.ecim-widget-summary__title a[href]")
        item_url = _safe_url(link.get("href")) if link is not None else None
        info = _try_item_url(item_url) or {}
        entity = info.get("entity") if info.get("entity") in _SUMMARY_ENTITIES else None
        picker = entry.select_one("input.es-entry-picker")
        entries.append(
            {
                "entry_id": _to_int(picker.get("value")) if picker is not None else None,
                "news_id": info.get("id") if entity == "news" else None,
                "news_url": item_url,
                "entity": entity,
                "item_url": item_url,
                "title": _text(link),
                "text": _text(entry.select_one("p.es-annotation-text")),
            }
        )
    out = _item_base(url)
    out.update({"month_name": _text(title), "entries": entries})
    return out
