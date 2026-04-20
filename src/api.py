"""Flask API server for the CI Monitor dashboard."""

import json
import logging
import os
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_from_directory
from flask_cors import CORS

from src.models.database import Database

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
DASHBOARD_DIST = PROJECT_ROOT / "dashboard" / "dist"

AUTH_ENV_VAR = "CI_MONITOR_API_KEY"
AUTH_HEADER = "X-API-Key"


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
            for s in segmenty:
                s["produktove_linie"] = [l for l in linie if l["segment_id"] == s["id"]]
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
            seg["spolecnosti"] = db.get_companies_in_segment(seg["id"])
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
            clanky = db.get_clanky(
                segment_id=seg["id"],
                competitor_id=args.get("spolecnost"),
                produktova_linie_id=args.get("produktova_linie"),
                typ_zpravy=args.get("typ_zpravy"),
                tag=args.get("tag"),
                od=args.get("od"),
                do=args.get("do"),
                limit=int(args.get("limit", 200)),
            )
            for c in clanky:
                c["tagy"] = _parse_json_field(c.get("tagy", "[]"))

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
            return jsonify(db.get_companies_in_segment(seg["id"]))
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
            for p in produkty:
                p["atributy"] = _parse_json_field(p.get("atributy", "{}"))
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
            for k in kampane:
                k["media_typy"] = _parse_json_field(k.get("media_typy", "[]"))
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
            return jsonify(db.get_mystery_shopping(
                segment_id=seg["id"],
                competitor_id=request.args.get("spolecnost"),
            ))
        finally:
            db.close()

    @app.route("/api/segment/<slug>/executive-summary")
    def api_segment_exec_summary(slug: str):
        db = get_db()
        try:
            seg = db.get_segment(slug)
            if not seg:
                abort(404)
            return jsonify(db.get_executive_summary(seg["id"]))
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
            clanek["tagy"] = _parse_json_field(clanek.get("tagy", "[]"))
            clanek["related"] = db.get_related_clanky(
                clanek_id, clanek.get("segment_id"),
            )
            for r in clanek["related"]:
                r["tagy"] = _parse_json_field(r.get("tagy", "[]"))
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
            detail["predstavenstvo"] = _parse_json_field(detail.get("predstavenstvo") or "[]")
            # Související obsah
            detail["clanky"] = db.get_clanky(competitor_id=competitor_id, limit=20)
            for c in detail["clanky"]:
                c["tagy"] = _parse_json_field(c.get("tagy", "[]"))
            detail["kampane"] = db.get_kampane(competitor_id=competitor_id)
            for k in detail["kampane"]:
                k["media_typy"] = _parse_json_field(k.get("media_typy", "[]"))
            detail["mystery_shopping"] = db.get_mystery_shopping(competitor_id=competitor_id)
            detail["produkty"] = db.get_produkty(competitor_id=competitor_id)
            return jsonify(detail)
        finally:
            db.close()

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
