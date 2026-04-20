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
