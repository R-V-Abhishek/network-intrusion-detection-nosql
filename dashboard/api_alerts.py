"""
Flask Blueprint for alert retrieval API endpoints.

Provides routes for fetching raw alert records from Cassandra,
filtered and paginated, for display in the dashboard alerts table.
"""

from flask import Blueprint, jsonify, request

from dashboard.storage import get_current_session_id, get_storage

api_alerts_bp = Blueprint("api_alerts", __name__)


@api_alerts_bp.get("/api/alerts")
def get_alerts():
    """Return recent alerts for a session with optional filtering."""
    session_id = request.args.get("session_id") or get_current_session_id()
    limit = int(request.args.get("limit", 100))
    attack_type = request.args.get("attack_type")

    alerts = get_storage().get_alerts(
        session_id=session_id,
        limit=limit,
        attack_type=attack_type,
    )
    return jsonify({"session_id": session_id, "count": len(alerts), "alerts": alerts})


@api_alerts_bp.get("/api/alerts/recent")
def get_recent_alerts():
    """Return a lightweight payload for dashboard live cards."""
    session_id = request.args.get("session_id") or get_current_session_id()
    limit = int(request.args.get("limit", 20))
    alerts = get_storage().get_alerts(session_id=session_id, limit=limit)
    return jsonify(alerts)
