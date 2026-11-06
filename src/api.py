"""Flask API server for the CI Monitor dashboard."""

import json
import logging
import os
import re
from pathlib import Path

from bs4 import BeautifulSoup, Comment, Tag
from flask import Flask, Response, abort, jsonify, request, send_from_directory
from flask_cors import CORS

from src.digest import build_digest, compute_period, render_html, render_markdown
from src.models.database import FINECIM_PLACEHOLDER_COMPETITOR, Database, load_subject_competitor_map

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DASHBOARD_DIST = PROJECT_ROOT / "dashboard" / "dist"

AUTH_ENV_VAR = "CI_MONITOR_API_KEY"
AUTH_HEADER = "X-API-Key"

# Tables reported by /api/finecim/status (FINeCIM-shaped content + scraper bookkeeping).
FINECIM_STATUS_TABLES = (
    "segmenty", "produktove_linie", "finecim_subjekty", "finecim_subjekty_segmenty",
    "clanky", "kampane", "kampane_kreativy", "mystery_shopping", "produkty", "produkty_verze",
    "executive_summary", "executive_summary_polozky", "spolecnost_detail",
    "finecim_vazby", "finecim_prilohy", "finecim_sync",
)

DIGEST_FORMATS = ("json", "md", "html")

# finecim_vazby.entity_type -> (table, ORDER BY clause, extra WHERE)
_RELATED_ENTITY_TABLES = {
    "clanek": ("clanky", "datum DESC", ""),
    "kampan": ("kampane", "COALESCE(aktualizace, zacatek) DESC", ""),
    "mystery": ("mystery_shopping", "datum DESC", ""),
    "produkt": ("produkty", "nazev", " AND aktivni = 1"),
}


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__, static_folder=None)
    CORS(app)

    if db_path is None:
        db_path = str(PROJECT_ROOT / "data" / "db" / "ci_monitor.sqlite")

    expected_key = os.environ.get(AUTH_ENV_VAR)
    if not expected_key:
        logger.warning(
            "%s not set — API endpoints are unauthenticated. "
            "Set the env var to require an %s header.",
            AUTH_ENV_VAR, AUTH_HEADER,
        )

    def get_db() -> Database:
        return Database(db_path)

    @app.before_request
    def _check_auth():
        if not expected_key:
            return None
        if not request.path.startswith("/api/"):
            return None
        provided = request.headers.get(AUTH_HEADER) or request.args.get("api_key")
        if provided != expected_key:
            abort(401, description="Invalid or missing API key")

    # ── API Routes ───────────────────────────────────────────

    @app.route("/api/signals")
    def api_signals():
        db = get_db()
        try:
            signals = db.get_signals(
                competitor_id=request.args.get("competitor"),
                source=request.args.get("source"),
                min_severity=_int_or_none(request.args.get("severity")),
                since=request.args.get("since"),
                limit=int(request.args.get("limit", 200)),
            )
            for sig in signals:
                sig["tags"] = _parse_json_field(sig.get("tags", "[]"))
                sig["metadata"] = _parse_json_field(sig.get("metadata", "{}"))
            return jsonify(signals)
        finally:
            db.close()

    @app.route("/api/competitors")
    def api_competitors():
        db = get_db()
        try:
            competitors = db.get_competitors()
            for comp in competitors:
                comp.update(db.get_competitor_signal_stats(comp["id"]))
            return jsonify(competitors)
        finally:
            db.close()

    @app.route("/api/status")
    def api_status():
        db = get_db()
        try:
            return jsonify(db.get_collector_status())
        finally:
            db.close()

    @app.route("/api/summary")
    def api_summary():
        db = get_db()
        try:
            overview = db.get_signals_overview()
            recent = db.get_signals(limit=15)
            for sig in recent:
                sig["tags"] = _parse_json_field(sig.get("tags", "[]"))
                sig["metadata"] = _parse_json_field(sig.get("metadata", "{}"))
            overview["recent_signals"] = recent
            return jsonify(overview)
        finally:
            db.close()

    # ── FINeCIM-inspirované endpointy (Czech-keyed) ──────────────

    @app.route("/api/segmenty")
    def api_segmenty():
        db = get_db()
        try:
            segmenty = db.get_segmenty()
            linie = db.get_produktove_linie()
            counts = _segment_counts(db)
            for s in segmenty:
                s["produktove_linie"] = [
                    linie_row for linie_row in linie if linie_row["segment_id"] == s["id"]
                ]
                s["spolecnosti"] = _segment_companies(db, s["id"])
                s["pocty"] = counts.get(s["id"], _empty_counts())
            return jsonify(segmenty)
        finally:
            db.close()

    @app.route("/api/segment/<slug>")
    def api_segment(slug: str):
        db = get_db()
        try:
            seg = db.get_segment(slug)
            if not seg:
                abort(404, description=f"Segment '{slug}' nenalezen")
            seg["produktove_linie"] = db.get_produktove_linie(seg["id"])
            seg["spolecnosti"] = _segment_companies(db, seg["id"])
            seg["pocty"] = _segment_counts(db).get(seg["id"], _empty_counts())
            return jsonify(seg)
        finally:
            db.close()

    @app.route("/api/segment/<slug>/novinky")
    def api_segment_novinky(slug: str):
        """Redakční feed + fallback na live signály (pokud žádné články zatím nejsou)."""
        db = get_db()
        try:
            seg = db.get_segment(slug)
            if not seg:
                abort(404)
            args = request.args
            limit = _int_or_none(args.get("limit")) or 200
            typ_zpravy = (args.get("typ_zpravy") or "").strip()
            clanky = db.get_clanky(
                segment_id=seg["id"],
                competitor_id=args.get("spolecnost"),
                produktova_linie_id=args.get("produktova_linie"),
                tag=args.get("tag"),
                od=args.get("od"),
                do=args.get("do"),
                # typ_zpravy holds several types joined with ", " -> filter here, unlimited first
                limit=0 if typ_zpravy else limit,
            )
            if typ_zpravy:
                wanted = typ_zpravy.casefold()
                clanky = [
                    c for c in clanky
                    if wanted in (t.casefold() for t in _split_types(c.get("typ_zpravy")))
                ][:limit]
            _decorate_clanky(db, clanky)

            # Fallback: pokud redakce ještě nic nemá, nabídni raw signály
            # (news + website — oboje se hodí jako výchozí research base)
            company_ids = [
                c["id"] for c in db.get_companies_in_segment(seg["id"])
            ]
            fallback_signaly = []
            if not clanky and company_ids:
                news_sig = db.get_signals(source="news", limit=200)
                web_sig = db.get_signals(source="website", limit=200)
                merged = news_sig + web_sig
                fallback_signaly = [
                    s for s in merged if s["competitor_id"] in company_ids
                ]
                fallback_signaly.sort(
                    key=lambda s: s.get("detected_at") or "",
                    reverse=True,
                )
                for sig in fallback_signaly:
                    sig["tags"] = _parse_json_field(sig.get("tags", "[]"))
                    sig["metadata"] = _parse_json_field(sig.get("metadata", "{}"))

            return jsonify({
                "clanky": clanky,
                "signaly_fallback": fallback_signaly,
            })
        finally:
            db.close()

    @app.route("/api/segment/<slug>/spolecnosti")
    def api_segment_spolecnosti(slug: str):
        db = get_db()
        try:
            seg = db.get_segment(slug)
            if not seg:
                abort(404)
            return jsonify(_segment_companies(db, seg["id"]))
        finally:
            db.close()

    @app.route("/api/segment/<slug>/produkty")
    def api_segment_produkty(slug: str):
        db = get_db()
        try:
            seg = db.get_segment(slug)
            if not seg:
                abort(404)
            args = request.args
            produkty = db.get_produkty(
                segment_id=seg["id"],
                competitor_id=args.get("spolecnost"),
                produktova_linie_id=args.get("produktova_linie"),
                zakaznicky_segment=args.get("zakaznicky_segment"),
            )
            _decorate_produkty(db, produkty)
            return jsonify(produkty)
        finally:
            db.close()

    @app.route("/api/segment/<slug>/kampane")
    def api_segment_kampane(slug: str):
        db = get_db()
        try:
            seg = db.get_segment(slug)
            if not seg:
                abort(404)
            args = request.args
            kampane = db.get_kampane(
                segment_id=seg["id"],
                competitor_id=args.get("spolecnost"),
                media_typ=args.get("media_typ"),
                od=args.get("od"),
                do=args.get("do"),
            )
            _decorate_kampane(db, kampane)
            return jsonify(kampane)
        finally:
            db.close()

    @app.route("/api/segment/<slug>/mystery-shopping")
    def api_segment_mystery(slug: str):
        db = get_db()
        try:
            seg = db.get_segment(slug)
            if not seg:
                abort(404)
            shops = db.get_mystery_shopping(
                segment_id=seg["id"],
                competitor_id=request.args.get("spolecnost"),
            )
            _decorate_mystery(db, shops)
            return jsonify(shops)
        finally:
            db.close()

    @app.route("/api/segment/<slug>/executive-summary")
    def api_segment_exec_summary(slug: str):
        db = get_db()
        try:
            seg = db.get_segment(slug)
            if not seg:
                abort(404)
            summaries = db.get_executive_summary(seg["id"])
            polozky = _summary_entries(db, [s["id"] for s in summaries])
            for s in summaries:
                s["polozky"] = polozky.get(s["id"], [])
            return jsonify(summaries)
        finally:
            db.close()

    @app.route("/api/segment/<slug>/analyzy")
    def api_segment_analyzy(slug: str):
        db = get_db()
        try:
            seg = db.get_segment(slug)
            if not seg:
                abort(404)
            rows = db.get_analyzy(seg["id"])
            for r in rows:
                r["soubory"] = _parse_json_field(r.get("soubory", "[]"))
            return jsonify(rows)
        finally:
            db.close()

    @app.route("/api/clanek/<clanek_id>")
    def api_clanek_detail(clanek_id: str):
        db = get_db()
        try:
            clanek = db.get_clanek(clanek_id)
            if not clanek:
                abort(404)
            _decorate_clanky(db, [clanek])
            if clanek["telo_format"] == "html":
                clanek["telo"] = sanitize_html(clanek.get("telo"))
            clanek["finecim_url"] = clanek.get("url") if _is_finecim(clanek_id) else None
            clanek["souvisejici_spolecnosti"] = _related_subjects(db, "clanek", clanek_id)
            clanek["prilohy"] = _attachments(db, "clanek", [clanek_id])
            clanek["related"] = db.get_related_clanky(
                clanek_id, clanek.get("segment_id"),
            )
            _decorate_clanky(db, clanek["related"])
            return jsonify(clanek)
        finally:
            db.close()

    @app.route("/api/spolecnost/<competitor_id>")
    def api_spolecnost_detail(competitor_id: str):
        db = get_db()
        try:
            detail = db.get_company_detail(competitor_id)
            if not detail:
                abort(404)
            detail["socialni_site"] = _parse_json_field(detail.get("socialni_site") or "{}")
            detail["predstavenstvo"] = _normalize_board(
                _parse_json_field(detail.get("predstavenstvo") or "[]")
            )
            subjects = _subjects_of_competitor(db, competitor_id)
            detail["finecim_subjekty"] = subjects
            detail["finecim_subject_id"] = subjects[0]["subject_id"] if subjects else None
            detail["finecim_url"] = next((s["url"] for s in subjects if s.get("url")), None)
            detail["logo_url"] = next((s["logo_url"] for s in subjects if s.get("logo_url")), None)
            prilohy_ids = [competitor_id]
            for s in subjects:
                prilohy_ids += [str(s["subject_id"]), f"fc-subject-{s['subject_id']}"]
            detail["prilohy"] = _attachments(db, "spolecnost", prilohy_ids)
            # Související obsah (přímá vazba competitor_id i FINeCIM „Související společnosti“)
            detail["clanky"] = _company_items(db, "clanek", competitor_id, limit=20)
            _decorate_clanky(db, detail["clanky"])
            detail["kampane"] = _company_items(db, "kampan", competitor_id)
            _decorate_kampane(db, detail["kampane"])
            detail["mystery_shopping"] = _company_items(db, "mystery", competitor_id)
            _decorate_mystery(db, detail["mystery_shopping"])
            detail["produkty"] = _company_items(db, "produkt", competitor_id)
            _decorate_produkty(db, detail["produkty"])
            detail["pocty"] = {
                "clanky": _company_item_count(db, "clanek", competitor_id),
                "kampane": _company_item_count(db, "kampan", competitor_id),
                "mystery_shopping": _company_item_count(db, "mystery", competitor_id),
                "produkty": _company_item_count(db, "produkt", competitor_id),
                "prilohy": len(detail["prilohy"]),
            }
            return jsonify(detail)
        finally:
            db.close()

    @app.route("/api/finecim/status")
    def api_finecim_status():
        db = get_db()
        try:
            sync_rows = [
                dict(r) for r in db.conn.execute(
                    "SELECT * FROM finecim_sync ORDER BY entity, segment_id"
                ).fetchall()
            ]
            pocty = {
                table: db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in FINECIM_STATUS_TABLES
            }
            last_success = max(
                (r["last_success_at"] for r in sync_rows if r.get("last_success_at")),
                default=None,
            )
            return jsonify({
                "sync": sync_rows,
                "pocty": pocty,
                "posledni_uspech": last_success,
            })
        finally:
            db.close()

    @app.route("/api/digest")
    def api_digest():
        """Digest konkurence za období: ?period=weekly|monthly&until=YYYY-MM-DD
        [&segment=slug]... [&format=json|md|html] (the same content as ``ci-monitor digest``)."""
        args = request.args
        fmt = (args.get("format") or "json").lower()
        if fmt not in DIGEST_FORMATS:
            abort(400, description=f"Neznámý formát: {fmt!r} (podporováno: {', '.join(DIGEST_FORMATS)})")
        try:
            period = compute_period(args.get("period") or "weekly", args.get("until") or None)
        except ValueError as exc:
            abort(400, description=str(exc))
        db = get_db()
        try:
            digest = build_digest(db, period, args.getlist("segment") or None)
        except ValueError as exc:
            abort(400, description=str(exc))
        finally:
            db.close()
        if fmt == "md":
            return Response(render_markdown(digest), mimetype="text/markdown")
        if fmt == "html":
            return Response(render_html(digest), mimetype="text/html")
        return jsonify(digest)

    # ── Static file serving (production) ─────────────────────

    @app.route("/", defaults={"path": ""})
    @app.route("/<path:path>")
    def serve_dashboard(path):
        if DASHBOARD_DIST.exists():
            file_path = DASHBOARD_DIST / path
            if file_path.is_file():
                return send_from_directory(str(DASHBOARD_DIST), path)
            return send_from_directory(str(DASHBOARD_DIST), "index.html")
        return jsonify({"error": "Dashboard not built. Run: cd dashboard && npm run build"}), 404

    return app


def _int_or_none(val: str | None) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def _parse_json_field(val) -> list | dict:
    if isinstance(val, (list, dict)):
        return val
    if isinstance(val, str) and val:
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            pass
    return []


# ── FINeCIM helpers ──────────────────────────────────────────────


def _is_finecim(item_id: str | None) -> bool:
    return bool(item_id) and str(item_id).startswith("fc-")


def _split_types(value: str | None) -> list[str]:
    """``typ_zpravy`` / ``typ_kampane`` are stored joined with ", "."""
    return [t.strip() for t in (value or "").split(",") if t.strip()]


def _marks(values) -> str:
    return ", ".join("?" for _ in values)


def _empty_counts() -> dict:
    return {"clanky": 0, "kampane": 0, "mystery_shopping": 0, "produkty": 0, "executive_summary": 0}


def _segment_counts(db: Database) -> dict[str, dict]:
    """segment_id -> number of items per content table."""
    result: dict[str, dict] = {}
    for table in ("clanky", "kampane", "mystery_shopping", "produkty", "executive_summary"):
        rows = db.conn.execute(
            f"SELECT segment_id, COUNT(*) AS n FROM {table} "
            "WHERE segment_id IS NOT NULL GROUP BY segment_id"
        ).fetchall()
        for r in rows:
            result.setdefault(r["segment_id"], _empty_counts())[table] = r["n"]
    return result


_COMPANY_EXTRA_COLUMNS = """
    (SELECT MIN(s.subject_id) FROM finecim_subjekty s
      WHERE s.competitor_id = c.id) AS finecim_subject_id,
    (SELECT s.logo_url FROM finecim_subjekty s
      WHERE s.competitor_id = c.id AND s.logo_url IS NOT NULL
      ORDER BY s.subject_id LIMIT 1) AS logo_url"""


def _segment_companies(db: Database, segment_id: str) -> list[dict]:
    """Competitors of a segment: configured membership plus FINeCIM subjects of the segment."""
    rows = db.conn.execute(
        f"""SELECT c.*, {_COMPANY_EXTRA_COLUMNS}
           FROM competitors c
           WHERE c.id != ? AND (
                 c.id IN (SELECT competitor_id FROM spolecnosti_segmenty WHERE segment_id = ?)
              OR c.id IN (SELECT s.competitor_id FROM finecim_subjekty s
                          JOIN finecim_subjekty_segmenty fs ON fs.subject_id = s.subject_id
                          WHERE fs.segment_id = ? AND s.competitor_id IS NOT NULL))
           ORDER BY c.tier, c.name""",
        (FINECIM_PLACEHOLDER_COMPETITOR, segment_id, segment_id),
    ).fetchall()
    return [dict(r) for r in rows]


def _company_refs(db: Database, competitor_ids) -> dict[str, dict]:
    """competitor id -> compact company reference (name, tier, logo, FINeCIM subject id)."""
    ids = sorted({c for c in competitor_ids if c})
    if not ids:
        return {}
    rows = db.conn.execute(
        f"""SELECT c.id, c.name, c.tier, c.parent_group, {_COMPANY_EXTRA_COLUMNS}
            FROM competitors c WHERE c.id IN ({_marks(ids)})""",
        ids,
    ).fetchall()
    return {r["id"]: dict(r) for r in rows}


def _attach_company(db: Database, rows: list[dict]) -> None:
    refs = _company_refs(db, (r.get("competitor_id") for r in rows))
    for r in rows:
        ref = refs.get(r.get("competitor_id"))
        r["spolecnost"] = ref
        r["spolecnost_nazev"] = ref["name"] if ref else None
        r["logo_url"] = ref["logo_url"] if ref else None


def _decorate_clanky(db: Database, clanky: list[dict]) -> None:
    for c in clanky:
        c["tagy"] = _parse_json_field(c.get("tagy", "[]"))
        c["typy_zpravy"] = _split_types(c.get("typ_zpravy"))
        telo = (c.get("telo") or "").lstrip()
        c["telo_format"] = "html" if telo.startswith("<") else "text"
    _attach_company(db, clanky)


def _decorate_kampane(db: Database, kampane: list[dict]) -> None:
    kreativy = _campaign_creatives(db, [k["id"] for k in kampane])
    for k in kampane:
        k["media_typy"] = _parse_json_field(k.get("media_typy", "[]"))
        k["typy_kampane"] = _split_types(k.get("typ_kampane"))
        k["kreativy"] = kreativy.get(k["id"], [])
    _attach_company(db, kampane)


def _decorate_mystery(db: Database, shops: list[dict]) -> None:
    prilohy = _attachments_by_entity(db, "mystery", [m["id"] for m in shops])
    for m in shops:
        m["prilohy"] = prilohy.get(m["id"], [])
    _attach_company(db, shops)


def _decorate_produkty(db: Database, produkty: list[dict]) -> None:
    linie_ids = sorted({p["produktova_linie_id"] for p in produkty if p.get("produktova_linie_id")})
    linie = {}
    if linie_ids:
        linie = {
            r["id"]: r["nazev"] for r in db.conn.execute(
                f"SELECT id, nazev FROM produktove_linie WHERE id IN ({_marks(linie_ids)})",
                linie_ids,
            ).fetchall()
        }
    for p in produkty:
        p["atributy"] = _parse_json_field(p.get("atributy", "[]"))
        p["atributy_mapa"] = _attribute_map(p["atributy"])
        p["produktova_linie_nazev"] = linie.get(p.get("produktova_linie_id"))
    _attach_company(db, produkty)


def _attribute_map(atributy) -> dict:
    """Flatten FINeCIM parameters (``[{section,name,value}]``) to ``{name: value}``.

    A name repeated in a later section is keyed ``"<section>: <name>"``. A dict (legacy
    shape) is returned unchanged."""
    if isinstance(atributy, dict):
        return atributy
    result: dict = {}
    for a in atributy or []:
        if not isinstance(a, dict) or not a.get("name"):
            continue
        key = a["name"]
        if key in result and a.get("section"):
            key = f"{a['section']}: {a['name']}"
        result.setdefault(key, a.get("value"))
    return result


def _campaign_creatives(db: Database, kampan_ids: list[str]) -> dict[str, list[dict]]:
    if not kampan_ids:
        return {}
    rows = db.conn.execute(
        f"""SELECT * FROM kampane_kreativy WHERE kampan_id IN ({_marks(kampan_ids)})
            ORDER BY kampan_id, COALESCE(datum, '') DESC, id""",
        kampan_ids,
    ).fetchall()
    result: dict[str, list[dict]] = {}
    for r in rows:
        result.setdefault(r["kampan_id"], []).append(dict(r))
    return result


def _attachments_by_entity(
    db: Database, entity_type: str, entity_ids: list[str],
) -> dict[str, list[dict]]:
    if not entity_ids:
        return {}
    rows = db.conn.execute(
        f"""SELECT id, entity_type, entity_id, nazev, url FROM finecim_prilohy
            WHERE entity_type = ? AND entity_id IN ({_marks(entity_ids)}) ORDER BY id""",
        (entity_type, *entity_ids),
    ).fetchall()
    result: dict[str, list[dict]] = {}
    for r in rows:
        result.setdefault(r["entity_id"], []).append(dict(r))
    return result


def _attachments(db: Database, entity_type: str, entity_ids: list[str]) -> list[dict]:
    """Attachments of one item stored under any of ``entity_ids``, de-duplicated by url."""
    seen: set[str] = set()
    result = []
    for rows in _attachments_by_entity(db, entity_type, list(dict.fromkeys(entity_ids))).values():
        for r in rows:
            if r["url"] not in seen:
                seen.add(r["url"])
                result.append(r)
    result.sort(key=lambda r: r["id"])
    return result


def _summary_entries(db: Database, summary_ids: list[str]) -> dict[str, list[dict]]:
    if not summary_ids:
        return {}
    rows = db.conn.execute(
        f"""SELECT p.*, c.url AS clanek_url, c.nazev AS clanek_nazev, c.datum AS clanek_datum
            FROM executive_summary_polozky p
            LEFT JOIN clanky c ON c.id = p.clanek_id
            WHERE p.summary_id IN ({_marks(summary_ids)})
            ORDER BY p.summary_id, COALESCE(p.poradi, 0), p.id""",
        summary_ids,
    ).fetchall()
    result: dict[str, list[dict]] = {}
    for r in rows:
        entry = dict(r)
        # typ: news | campaign | mystery-shopping | produkt | None (rows stored before typ existed
        # are news entries when they reference a clanek).
        is_news = entry.get("typ") in (None, "news")
        if not is_news:
            # Entries linking to a campaign / mystery report / product have no clanek; the
            # dashboard links them to the FINeCIM page via "url".
            entry["clanek_url"] = entry["clanek_nazev"] = entry["clanek_datum"] = None
        entry["clanek_existuje"] = is_news and entry.get("clanek_nazev") is not None
        entry["url"] = entry.get("url") or entry.get("clanek_url")
        result.setdefault(r["summary_id"], []).append(entry)
    return result


def _related_subjects(db: Database, entity_type: str, entity_id: str) -> list[dict]:
    """FINeCIM „Související společnosti“ of an item, resolved to competitors where possible."""
    rows = db.conn.execute(
        """SELECT v.subject_id, s.nazev, s.url, s.logo_url, s.competitor_id
           FROM finecim_vazby v
           LEFT JOIN finecim_subjekty s ON s.subject_id = v.subject_id
           WHERE v.entity_type = ? AND v.entity_id = ?
           ORDER BY v.rowid""",
        (entity_type, entity_id),
    ).fetchall()
    result = [dict(r) for r in rows]
    if not result:
        return result
    mapping = load_subject_competitor_map()
    for r in result:
        if not r.get("competitor_id"):
            r["competitor_id"] = mapping.get(int(r["subject_id"]))
    refs = _company_refs(db, (r["competitor_id"] for r in result))
    for r in result:
        ref = refs.get(r["competitor_id"])
        if not ref:
            r["competitor_id"] = None
        r["competitor_name"] = ref["name"] if ref else None
        r["tier"] = ref["tier"] if ref else None
        r["nazev"] = r.get("nazev") or r["competitor_name"]
    return result


def _subjects_of_competitor(db: Database, competitor_id: str) -> list[dict]:
    rows = db.conn.execute(
        """SELECT subject_id, nazev, url, logo_url, aktualizace FROM finecim_subjekty
           WHERE competitor_id = ? ORDER BY subject_id""",
        (competitor_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _company_items_where(entity_type: str) -> tuple[str, str, str]:
    table, order, extra = _RELATED_ENTITY_TABLES[entity_type]
    where = (
        "(competitor_id = ? OR id IN ("
        "SELECT v.entity_id FROM finecim_vazby v "
        "JOIN finecim_subjekty s ON s.subject_id = v.subject_id "
        "WHERE v.entity_type = ? AND s.competitor_id = ?))" + extra
    )
    return table, where, order


def _company_items(
    db: Database, entity_type: str, competitor_id: str, limit: int | None = None,
) -> list[dict]:
    """Items whose primary company is ``competitor_id`` or that list it as a related company."""
    table, where, order = _company_items_where(entity_type)
    query = f"SELECT * FROM {table} WHERE {where} ORDER BY {order}"
    params: list = [competitor_id, entity_type, competitor_id]
    if limit:
        query += " LIMIT ?"
        params.append(limit)
    return [dict(r) for r in db.conn.execute(query, params).fetchall()]


def _company_item_count(db: Database, entity_type: str, competitor_id: str) -> int:
    table, where, _ = _company_items_where(entity_type)
    return db.conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {where}",
        (competitor_id, entity_type, competitor_id),
    ).fetchone()[0]


def _normalize_board(board) -> list[dict]:
    """Board members as ``{jmeno, role}`` (the scraper stores ``{name, role}``)."""
    result = []
    for m in board if isinstance(board, list) else []:
        if isinstance(m, str):
            result.append({"jmeno": m, "role": None})
        elif isinstance(m, dict):
            entry = dict(m)
            entry.setdefault("jmeno", m.get("name"))
            entry.setdefault("role", None)
            result.append(entry)
    return result


# Defence in depth: the scraper already sanitises ``clanky.telo``; the dashboard injects it
# as HTML, so the same allow-list is re-applied before serving it.
_SAFE_TAGS = frozenset({
    "p", "br", "strong", "b", "em", "i", "u", "a", "ul", "ol", "li", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "table", "thead", "tbody", "tr", "th", "td", "img",
})
_DROP_WITH_CONTENT = frozenset({
    "script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math",
})
_SAFE_ATTRS = {
    "a": ("href", "title"), "img": ("src", "alt", "title"),
    "td": ("colspan", "rowspan"), "th": ("colspan", "rowspan"),
}
_SAFE_URL = re.compile(r"^(https?://|/(?!/)|#|mailto:)", re.IGNORECASE)


def sanitize_html(html: str | None) -> str | None:
    """Reduce HTML to the FINeCIM body allow-list (tags, attributes, http(s)/relative links)."""
    if not html:
        return html
    soup = BeautifulSoup(html, "html.parser")
    for comment in soup.find_all(string=lambda s: isinstance(s, Comment)):
        comment.extract()
    for tag in list(soup.find_all(True)):
        if not isinstance(tag, Tag) or tag.decomposed:
            continue
        name = (tag.name or "").lower()
        if name in _DROP_WITH_CONTENT:
            tag.decompose()
            continue
        if name not in _SAFE_TAGS:
            tag.unwrap()
            continue
        allowed = _SAFE_ATTRS.get(name, ())
        for attr in list(tag.attrs):
            unsafe_url = attr in ("href", "src") and not _SAFE_URL.match(str(tag.attrs[attr]).strip())
            if attr not in allowed or unsafe_url:
                del tag.attrs[attr]
        if name == "a" and tag.get("href"):
            tag["target"] = "_blank"
            tag["rel"] = "noopener noreferrer"
    return str(soup)
