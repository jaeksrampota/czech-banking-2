"""Build the competitor digest for a period from the FINeCIM-shaped tables.

The digest is a JSON-serialisable dict with Czech keys (like the API) and four parts:

1. ``spolecnosti[*].pocty`` – headline numbers per competitor (articles, campaigns started
   or updated, product changes, mystery-shopping reports);
2. ``spolecnosti[*]`` – "co je nové" per competitor: products (new, or a diff of
   ``produkty.atributy`` against the previously stored version), campaigns with media
   types and the first creative, news grouped by ``typ_zpravy``, mystery-shopping
   reports with their PDF;
3. ``executive_summary`` – entries of the monthly editorial summaries overlapping the
   period, per domain;
4. ``trh`` – market-level news (no competitor, or the "Bankovní trh" domain).

Competitors are ordered by ``rank_key`` (tier first by default, see ``rank_by_tier``), so a
threat score can replace the ordering later without touching the rest.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from dateutil.relativedelta import relativedelta

from src.models.database import FINECIM_PLACEHOLDER_COMPETITOR, Database

PERIODS = ("weekly", "monthly")
PERIOD_NAMES = {"weekly": "Týdenní digest", "monthly": "Měsíční digest"}
PERIOD_ADJECTIVES = {"weekly": "týdenní", "monthly": "měsíční"}

# Domain whose news is market-level rather than competitor-level (config/segments.yaml slug).
MARKET_SEGMENT_SLUG = "bankovni-trh"
FINECIM_BASE_URL = "https://www.finecim.cz"
# Group label for news without ``typ_zpravy``.
OTHER_NEWS_TYPE = "ostatní"

CZECH_MONTHS = (
    "leden", "únor", "březen", "duben", "květen", "červen",
    "červenec", "srpen", "září", "říjen", "listopad", "prosinec",
)

# Items without a url column: the FINeCIM page is derived from the id and the domain slug.
_FINECIM_ID = re.compile(r"^fc-(campaign|ms)-(\d+)$")
_FINECIM_PATHS = {"campaign": "campaign", "ms": "mystery-shopping"}


# ── period ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Period:
    """A closed date range ``od``..``do`` (both inclusive) of type ``weekly`` or ``monthly``."""

    typ: str
    od: date
    do: date

    @property
    def nazev(self) -> str:
        return PERIOD_NAMES[self.typ]

    @property
    def popis(self) -> str:
        return format_range_cz(self.od, self.do)

    def contains(self, value: str | date | None) -> bool:
        """True when the ISO date (or the date part of an ISO datetime) lies in the period."""
        if not value:
            return False
        day = value.isoformat()[:10] if isinstance(value, date) else str(value)[:10]
        return self.od.isoformat() <= day <= self.do.isoformat()

    def as_dict(self) -> dict:
        return {
            "typ": self.typ,
            "od": self.od.isoformat(),
            "do": self.do.isoformat(),
            "nazev": self.nazev,
            "popis": self.popis,
        }


def parse_date(value: date | datetime | str) -> date:
    """``YYYY-MM-DD`` (a longer ISO string is cut to its date part) or a date/datetime."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError as exc:
        raise ValueError(f"Neplatné datum: {value!r} (očekává se YYYY-MM-DD)") from exc


def compute_period(typ: str, until: date | datetime | str | None = None) -> Period:
    """The period of type ``typ`` ending at ``until`` (default today).

    ``weekly`` is the 7 days ending at ``until``; ``monthly`` is one calendar month
    ending at ``until`` (``2026-11-06`` -> ``2026-10-07``..``2026-11-06``)."""
    if typ not in PERIODS:
        raise ValueError(f"Neznámé období: {typ!r} (podporováno: {', '.join(PERIODS)})")
    end = parse_date(until) if until else date.today()
    span = timedelta(days=6) if typ == "weekly" else relativedelta(months=1, days=-1)
    return Period(typ, end - span, end)


def format_date_cz(value: date | str | None) -> str:
    """``2026-11-06`` -> ``6. 11. 2026``; an unparsable value is returned as is."""
    if value is None or value == "":
        return "—"
    try:
        d = parse_date(value)
    except ValueError:
        return str(value)
    return f"{d.day}. {d.month}. {d.year}"


def format_range_cz(od: date, do: date) -> str:
    if od.year == do.year:
        return f"{od.day}. {od.month}. – {do.day}. {do.month}. {do.year}"
    return f"{format_date_cz(od)} – {format_date_cz(do)}"


# ── ranking (pluggable) ──────────────────────────────────────────

RankKey = Callable[[dict], tuple]


def rank_by_tier(spolecnost: dict) -> tuple:
    """Default competitor order: tier 1 first, then by name; the FINeCIM placeholder last.

    Replace it (``build_digest(..., rank_key=...)``) once a threat score exists."""
    placeholder = spolecnost.get("id") == FINECIM_PLACEHOLDER_COMPETITOR
    return (placeholder, spolecnost.get("tier") or 99, (spolecnost.get("nazev") or "").casefold())


# ── product parameter diff ───────────────────────────────────────


def _attribute_map(atributy) -> dict[tuple[str | None, str], str | None]:
    """``[{section, name, value}]`` (or the legacy ``{name: value}``) -> ``{(section, name): value}``."""
    result: dict[tuple[str | None, str], str | None] = {}
    if isinstance(atributy, dict):
        for name, value in atributy.items():
            result[(None, str(name))] = _text_or_none(value)
        return result
    for a in atributy or []:
        if isinstance(a, dict) and a.get("name"):
            result[(a.get("section") or None, str(a["name"]))] = _text_or_none(a.get("value"))
    return result


def _text_or_none(value) -> str | None:
    return None if value is None else str(value).strip()


def _normalised(value: str | None) -> str:
    return " ".join((value or "").split())


def diff_atributy(old, new) -> list[dict]:
    """Changes from ``old`` to ``new`` product parameters.

    Each change is ``{"section", "name", "stara", "nova", "druh"}`` with ``druh`` one of
    ``zmena`` (value changed), ``pridano`` (parameter new) or ``odebrano`` (parameter
    gone); whitespace-only differences are ignored. Order: current parameters first, then
    removed ones."""
    old_map = _attribute_map(old)
    new_map = _attribute_map(new)
    changes: list[dict] = []
    for (section, name), value in new_map.items():
        if (section, name) not in old_map:
            changes.append({"section": section, "name": name, "stara": None, "nova": value, "druh": "pridano"})
        elif _normalised(old_map[(section, name)]) != _normalised(value):
            changes.append({"section": section, "name": name, "stara": old_map[(section, name)],
                            "nova": value, "druh": "zmena"})
    for (section, name), value in old_map.items():
        if (section, name) not in new_map:
            changes.append({"section": section, "name": name, "stara": value, "nova": None, "druh": "odebrano"})
    return changes


# ── helpers ──────────────────────────────────────────────────────


def _split_types(value: str | None) -> list[str]:
    """``typ_zpravy`` / ``typ_kampane`` hold several types joined with ", "."""
    return [t.strip() for t in (value or "").split(",") if t.strip()]


def _json_value(value):
    """A JSON column (text) -> list/dict; anything unparsable -> ``[]``."""
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        return parsed if isinstance(parsed, (list, dict)) else []
    return []


def _json_list(value) -> list:
    parsed = _json_value(value)
    return parsed if isinstance(parsed, list) else []


def _day(value: str | None) -> str | None:
    return str(value)[:10] if value else None


def _marks(values) -> str:
    return ", ".join("?" for _ in values)


def _month_range(rok: int, mesic: int) -> tuple[date, date]:
    first = date(rok, mesic, 1)
    last = first + relativedelta(months=1) - timedelta(days=1)
    return first, last


# ── builder ──────────────────────────────────────────────────────


def build_digest(
    db: Database,
    period: Period,
    segments: Iterable[str] | None = None,
    *,
    rank_key: RankKey = rank_by_tier,
) -> dict:
    """Build the digest dict for ``period``; ``segments`` are segment slugs (all when empty).

    Raises ``ValueError`` for an unknown segment slug."""
    return _DigestBuilder(db, period, list(segments or []), rank_key).build()


class _DigestBuilder:
    def __init__(self, db: Database, period: Period, segment_slugs: list[str], rank_key: RankKey) -> None:
        self.db = db
        self.period = period
        self.rank_key = rank_key
        self.segmenty: dict[str, dict] = {
            r["id"]: dict(r) for r in db.conn.execute("SELECT * FROM segmenty ORDER BY poradi, nazev")
        }
        by_slug = {s["slug"]: s for s in self.segmenty.values()}
        self.segment_slugs = list(dict.fromkeys(s.strip() for s in segment_slugs if s and s.strip()))
        unknown = [s for s in self.segment_slugs if s not in by_slug]
        if unknown:
            raise ValueError(
                f"Neznámý segment: {', '.join(unknown)} (k dispozici: {', '.join(sorted(by_slug))})"
            )
        self.segment_ids: list[str] | None = (
            [by_slug[s]["id"] for s in self.segment_slugs] if self.segment_slugs else None
        )
        market = by_slug.get(MARKET_SEGMENT_SLUG)
        self.market_segment_id = market["id"] if market else None
        self.competitors: dict[str, dict] = {
            r["id"]: dict(r) for r in db.conn.execute("SELECT * FROM competitors")
        }
        self.companies: dict[str, dict] = {}
        self._news_by_company: dict[str, list[dict]] = {}
        self._market_news: list[dict] = []

    # ── small helpers ────────────────────────────────────────────

    def _segment_ref(self, segment_id: str | None) -> dict | None:
        seg = self.segmenty.get(segment_id) if segment_id else None
        if not seg:
            return None
        return {"id": seg["id"], "slug": seg["slug"], "nazev": seg["nazev"]}

    def _segment_clause(self, column: str = "segment_id") -> tuple[str, list]:
        if self.segment_ids is None:
            return "", []
        return f" AND {column} IN ({_marks(self.segment_ids)})", list(self.segment_ids)

    def _finecim_url(self, item_id: str, segment_id: str | None) -> str | None:
        match = _FINECIM_ID.match(item_id or "")
        seg = self.segmenty.get(segment_id) if segment_id else None
        if not match or not seg:
            return None
        slug = seg.get("finecim_slug") or seg["slug"]
        return f"{FINECIM_BASE_URL}/cz/domena/{slug}/{_FINECIM_PATHS[match.group(1)]}/{match.group(2)}"

    def _company_ref(self, competitor_id: str | None) -> dict | None:
        comp = self.competitors.get(competitor_id) if competitor_id else None
        if not comp:
            return None
        return {"id": comp["id"], "nazev": comp["name"], "tier": comp["tier"]}

    def _company(self, competitor_id: str) -> dict:
        """The digest entry of a competitor, created on first use."""
        entry = self.companies.get(competitor_id)
        if entry is None:
            comp = self.competitors.get(competitor_id)
            if comp is None:
                name = "FINeCIM (nepřiřazeno)" if competitor_id == FINECIM_PLACEHOLDER_COMPETITOR else competitor_id
                comp = {"id": competitor_id, "name": name, "tier": None, "parent_group": None}
            entry = {
                "id": competitor_id,
                "nazev": comp["name"],
                "tier": comp["tier"],
                "parent_group": comp.get("parent_group"),
                "pocty": {"clanky": 0, "kampane": 0, "produkty": 0, "mystery_shopping": 0},
                "produkty": [],
                "kampane": [],
                "zpravy": [],
                "mystery_shopping": [],
            }
            self.companies[competitor_id] = entry
        return entry

    def _is_market_news(self, row: dict) -> bool:
        competitor = row.get("competitor_id")
        if not competitor or competitor == FINECIM_PLACEHOLDER_COMPETITOR:
            return True
        return self.market_segment_id is not None and row.get("segment_id") == self.market_segment_id

    # ── sections ─────────────────────────────────────────────────

    def build(self) -> dict:
        self._collect_news()
        self._collect_campaigns()
        self._collect_products()
        self._collect_mystery()
        summaries = self._collect_summaries()

        for competitor_id, items in self._news_by_company.items():
            company = self._company(competitor_id)
            company["zpravy"] = _group_news(items)
            company["pocty"]["clanky"] = len(items)
        companies = sorted(self.companies.values(), key=self.rank_key)
        trh = _group_news(self._market_news)

        souhrn = {
            "spolecnosti": len(companies),
            "clanky": sum(c["pocty"]["clanky"] for c in companies),
            "kampane": sum(c["pocty"]["kampane"] for c in companies),
            "produkty": sum(c["pocty"]["produkty"] for c in companies),
            "mystery_shopping": sum(c["pocty"]["mystery_shopping"] for c in companies),
            "executive_summary": len(summaries),
            "trh": len(self._market_news),
        }
        prazdny = not companies and not summaries and not self._market_news
        segment_refs = [
            self._segment_ref(seg_id) for seg_id in (self.segment_ids or list(self.segmenty))
        ]
        return {
            "period": self.period.as_dict(),
            "segmenty": [s for s in segment_refs if s],
            "filtr_segmentu": list(self.segment_slugs),
            "vygenerovano": datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds"),
            "prazdny": prazdny,
            "souhrn": souhrn,
            "spolecnosti": companies,
            "executive_summary": summaries,
            "trh": trh,
        }

    def _collect_news(self) -> None:
        clause, params = self._segment_clause()
        rows = self.db.conn.execute(
            f"SELECT * FROM clanky WHERE datum BETWEEN ? AND ?{clause} ORDER BY datum DESC, nazev",
            [self.period.od.isoformat(), self.period.do.isoformat(), *params],
        ).fetchall()
        for r in rows:
            row = dict(r)
            item = {
                "id": row["id"],
                "nazev": row["nazev"],
                "datum": _day(row.get("datum")),
                "url": row.get("url"),
                "perex": row.get("perex"),
                "typy_zpravy": _split_types(row.get("typ_zpravy")),
                "tagy": [str(t) for t in _json_list(row.get("tagy"))],
                "stav": row.get("stav"),
                "segment": self._segment_ref(row.get("segment_id")),
                "spolecnost": self._company_ref(row.get("competitor_id")),
            }
            if self._is_market_news(row):
                self._market_news.append(item)
            else:
                self._news_by_company.setdefault(row["competitor_id"], []).append(item)

    def _collect_campaigns(self) -> None:
        clause, params = self._segment_clause()
        od, do = self.period.od.isoformat(), self.period.do.isoformat()
        rows = self.db.conn.execute(
            f"""SELECT * FROM kampane
                WHERE ((zacatek BETWEEN ? AND ?) OR (aktualizace BETWEEN ? AND ?)
                       OR (zacatek IS NULL AND aktualizace IS NULL
                           AND substr(pridano_at, 1, 10) BETWEEN ? AND ?)){clause}
                ORDER BY COALESCE(aktualizace, zacatek, pridano_at) DESC, nazev""",
            [od, do, od, do, od, do, *params],
        ).fetchall()
        creatives = self._creatives([r["id"] for r in rows])
        for r in rows:
            row = dict(r)
            if self.period.contains(row.get("zacatek")):
                druh = "nova"
            elif self.period.contains(row.get("aktualizace")):
                druh = "aktualizovana"
            else:
                druh = "nova"
            kreativy = creatives.get(row["id"], [])
            company = self._company(row["competitor_id"])
            company["kampane"].append({
                "id": row["id"],
                "nazev": row["nazev"],
                "url": self._finecim_url(row["id"], row.get("segment_id")),
                "druh": druh,
                "segment": self._segment_ref(row.get("segment_id")),
                "zacatek": _day(row.get("zacatek")),
                "aktualizace": _day(row.get("aktualizace")),
                "popis": row.get("popis"),
                "media_typy": [str(m) for m in _json_list(row.get("media_typy"))],
                "typy_kampane": _split_types(row.get("typ_kampane")),
                "kreativa_url": row.get("kreativa_url"),
                "prvni_kreativa": kreativy[0] if kreativy else None,
                "pocet_kreativ": len(kreativy),
            })
            company["pocty"]["kampane"] += 1

    def _creatives(self, kampan_ids: list[str]) -> dict[str, list[dict]]:
        """Creatives per campaign, earliest first (the first creative is the launch one)."""
        if not kampan_ids:
            return {}
        rows = self.db.conn.execute(
            f"""SELECT id, kampan_id, datum, media_typ, popis, media_url, media_druh
                FROM kampane_kreativy WHERE kampan_id IN ({_marks(kampan_ids)})
                ORDER BY kampan_id, COALESCE(datum, '9999-12-31'), id""",
            kampan_ids,
        ).fetchall()
        result: dict[str, list[dict]] = {}
        for r in rows:
            result.setdefault(r["kampan_id"], []).append({
                "id": r["id"], "datum": _day(r["datum"]), "media_typ": r["media_typ"],
                "popis": r["popis"], "media_url": r["media_url"], "media_druh": r["media_druh"],
            })
        return result

    def _collect_products(self) -> None:
        clause, params = self._segment_clause()
        od, do = self.period.od.isoformat(), self.period.do.isoformat()
        where = """(COALESCE(aktualizace, substr(pridano_at, 1, 10)) BETWEEN ? AND ?
                    OR substr(pridano_at, 1, 10) BETWEEN ? AND ?"""
        query_params = [od, do, od, do]
        if self.db.has_table("produkty_verze"):
            # a later version stored in the period (FINeCIM did not necessarily bump the date)
            where += """ OR id IN (SELECT v.produkt_id FROM produkty_verze v
                                    WHERE substr(v.zachyceno_at, 1, 10) BETWEEN ? AND ?
                                      AND v.id > (SELECT MIN(w.id) FROM produkty_verze w
                                                  WHERE w.produkt_id = v.produkt_id))"""
            query_params += [od, do]
        where += ")"
        rows = self.db.conn.execute(
            f"SELECT * FROM produkty WHERE aktivni = 1 AND {where}{clause} ORDER BY nazev, id",
            [*query_params, *params],
        ).fetchall()
        linie = {
            r["id"]: r["nazev"] for r in self.db.conn.execute("SELECT id, nazev FROM produktove_linie")
        }
        for r in rows:
            row = dict(r)
            current = _json_value(row.get("atributy"))
            druh, zmeny = self._classify_product(row, current)
            company = self._company(row["competitor_id"])
            company["produkty"].append({
                "id": row["id"],
                "nazev": row["nazev"],
                "url": row.get("url"),
                "druh": druh,
                "segment": self._segment_ref(row.get("segment_id")),
                "produktova_linie": linie.get(row.get("produktova_linie_id")),
                "zakaznicky_segment": row.get("zakaznicky_segment"),
                "kratky_popis": row.get("kratky_popis"),
                "aktualizace": _day(row.get("aktualizace")),
                "pridano": _day(row.get("pridano_at")),
                "zmeny": zmeny,
                "parametry": [
                    {"section": section, "name": name, "value": value}
                    for (section, name), value in _attribute_map(current).items()
                ],
            })
            company["pocty"]["produkty"] += 1

    def _classify_product(self, row: dict, current) -> tuple[str, list[dict]]:
        """``novy`` (first stored in the period), ``zmena`` (parameters differ from the
        previous version, with the diff) or ``aktualizace`` (updated, nothing to diff)."""
        if self.period.contains(row.get("pridano_at")):
            return "novy", []
        versions = self.db.get_produkt_verze(row["id"])
        if len(versions) < 2:
            return "aktualizace", []
        latest = versions[-1]
        earlier = versions[:-1]
        before_period = [
            v for v in earlier
            if (_day(v.get("aktualizace")) or _day(v.get("zachyceno_at")) or "") < self.period.od.isoformat()
        ]
        previous = before_period[-1] if before_period else earlier[0]
        if previous["content_hash"] == latest["content_hash"]:
            return "aktualizace", []
        zmeny = diff_atributy(previous["atributy"], latest["atributy"])
        return ("zmena", zmeny) if zmeny else ("aktualizace", [])

    def _collect_mystery(self) -> None:
        clause, params = self._segment_clause()
        rows = self.db.conn.execute(
            f"""SELECT * FROM mystery_shopping WHERE datum BETWEEN ? AND ?{clause}
                ORDER BY datum DESC, nazev""",
            [self.period.od.isoformat(), self.period.do.isoformat(), *params],
        ).fetchall()
        attachments = self._mystery_attachments([r["id"] for r in rows])
        for r in rows:
            row = dict(r)
            # a report without a company is listed under the FINeCIM placeholder (last in order)
            company = self._company(row.get("competitor_id") or FINECIM_PLACEHOLDER_COMPETITOR)
            company["mystery_shopping"].append({
                "id": row["id"],
                "nazev": row["nazev"],
                "datum": _day(row.get("datum")),
                "popis": row.get("popis"),
                "pdf_url": row.get("pdf_url") or attachments.get(row["id"]),
                "url": self._finecim_url(row["id"], row.get("segment_id")),
                "segment": self._segment_ref(row.get("segment_id")),
            })
            company["pocty"]["mystery_shopping"] += 1

    def _mystery_attachments(self, ids: list[str]) -> dict[str, str]:
        """First attached PDF per mystery-shopping report (fallback for a missing pdf_url)."""
        if not ids or not self.db.has_table("finecim_prilohy"):
            return {}
        rows = self.db.conn.execute(
            f"""SELECT entity_id, url FROM finecim_prilohy
                WHERE entity_type = 'mystery' AND entity_id IN ({_marks(ids)}) ORDER BY id""",
            ids,
        ).fetchall()
        result: dict[str, str] = {}
        for r in rows:
            result.setdefault(r["entity_id"], r["url"])
        return result

    def _collect_summaries(self) -> list[dict]:
        clause, params = self._segment_clause()
        rows = self.db.conn.execute(
            f"SELECT * FROM executive_summary WHERE 1=1{clause} ORDER BY rok DESC, mesic DESC, segment_id",
            params,
        ).fetchall()
        wanted = []
        for r in rows:
            row = dict(r)
            try:
                first, last = _month_range(int(row["rok"]), int(row["mesic"]))
            except (TypeError, ValueError):
                continue
            if first <= self.period.do and last >= self.period.od:
                wanted.append(row)
        entries = self._summary_entries([s["id"] for s in wanted])
        result = []
        for row in wanted:
            mesic = int(row["mesic"])
            nazev = row.get("nazev") or f"{CZECH_MONTHS[mesic - 1]} {row['rok']}"
            result.append({
                "id": row["id"],
                "rok": int(row["rok"]),
                "mesic": mesic,
                "nazev": nazev,
                "pdf_url": row.get("pdf_url"),
                "segment": self._segment_ref(row.get("segment_id")),
                "polozky": entries.get(row["id"], []),
            })
        # per domain (segment order), newest month first
        order = {seg_id: i for i, seg_id in enumerate(self.segmenty)}
        result.sort(key=lambda s: (order.get(s["segment"]["id"] if s["segment"] else "", 999),
                                   -s["rok"], -s["mesic"]))
        return result

    def _summary_entries(self, summary_ids: list[str]) -> dict[str, list[dict]]:
        if not summary_ids:
            return {}
        rows = self.db.conn.execute(
            f"""SELECT p.*, c.url AS clanek_url FROM executive_summary_polozky p
                LEFT JOIN clanky c ON c.id = p.clanek_id
                WHERE p.summary_id IN ({_marks(summary_ids)})
                ORDER BY p.summary_id, COALESCE(p.poradi, 0), p.id""",
            summary_ids,
        ).fetchall()
        result: dict[str, list[dict]] = {}
        for r in rows:
            row = dict(r)  # url / typ are missing on a database created before those columns
            result.setdefault(row["summary_id"], []).append({
                "id": row["id"],
                "nazev": row.get("nazev"),
                "text": row.get("text"),
                "url": row.get("url") or row.get("clanek_url"),
                "typ": row.get("typ"),
                "clanek_id": row.get("clanek_id"),
            })
        return result


def _group_news(items: list[dict]) -> list[dict]:
    """Group news by their primary ``typ_zpravy``: ``[{"typ", "polozky"}]``, types sorted
    alphabetically with ``ostatní`` (no type) last; items keep their date order."""
    groups: dict[str, list[dict]] = {}
    for item in items:
        typ = item["typy_zpravy"][0] if item.get("typy_zpravy") else OTHER_NEWS_TYPE
        groups.setdefault(typ, []).append(item)
    ordered = sorted(groups, key=lambda t: (t == OTHER_NEWS_TYPE, t.casefold()))
    return [{"typ": typ, "polozky": groups[typ]} for typ in ordered]
