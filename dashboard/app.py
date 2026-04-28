"""Flask app entrypoint for dashboard APIs and pages."""

from __future__ import annotations

import os
import subprocess

from flask import Flask, jsonify, render_template, request

from dashboard.api_alerts import api_alerts_bp
from dashboard.api_analytics import api_analytics_bp
from dashboard.storage import (
    clear_session,
    get_current_session_id,
    get_storage,
    set_current_session_id,
    start_new_session,
)


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates")

    storage = get_storage()
    storage.connect()
    storage.register_session(get_current_session_id(), dataset="unsw")

    app.register_blueprint(api_alerts_bp)
    app.register_blueprint(api_analytics_bp)

    @app.get("/")
    def dashboard_home():
        return render_template("dashboard.html")

    @app.get("/alerts")
    def alerts_page():
        return render_template("alerts.html")

    @app.get("/analytics")
    def analytics_page():
        return render_template("analytics.html")

    @app.get("/settings")
    def settings_page():
        return render_template("settings.html")

    @app.get("/api/health")
    def api_health():
        try:
            commit = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                stderr=subprocess.DEVNULL,
            ).decode().strip()
        except Exception:
            commit = "unknown"
        return jsonify(
            {"status": "ok", "commit": commit, "services": {"storage": "connected"}}
        )

    @app.get("/api/sessions")
    def api_sessions():
        limit = int(request.args.get("limit", 10))
        return jsonify(storage.get_sessions(limit=limit))

    @app.get("/api/session/current")
    def api_session_current():
        return jsonify({"session_id": get_current_session_id()})

    @app.post("/api/session/set")
    def api_session_set():
        payload = request.get_json(silent=True) or {}
        session_id = payload.get("session_id")
        if not session_id:
            return jsonify({"error": "session_id is required"}), 400
        set_current_session_id(session_id)
        storage.register_session(session_id, dataset="unsw")
        return jsonify({"session_id": session_id})

    @app.post("/api/session/new")
    def api_session_new():
        session_id = start_new_session()
        storage.register_session(session_id, dataset="unsw")
        return jsonify({"session_id": session_id})

    @app.delete("/api/session/delete")
    def api_session_delete():
        session_id = request.args.get("session_id") or get_current_session_id()
        result = storage.delete_session(session_id)
        return jsonify(result)

    @app.delete("/api/sessions/delete-all")
    def api_sessions_delete_all():
        clear_session()
        result = storage.delete_all_sessions()
        return jsonify(result)

    return app


app = create_app()


if __name__ == "__main__":
    debug_mode = os.getenv("DASHBOARD_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=5000, debug=debug_mode, use_reloader=False)
