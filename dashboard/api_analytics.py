"""
Flask Blueprint for analytics and statistics API endpoints.

Provides aggregated stats, timelines, and per-attack-type breakdowns
sourced from Cassandra counter tables and Redis sorted sets.
"""

from flask import Blueprint, jsonify, request

from config.config import UNSW_ATTACK_TYPE_MAPPING
from dashboard.storage import get_storage, get_current_session_id

api_analytics_bp = Blueprint("api_analytics", __name__)


@api_analytics_bp.get("/api/alerts/stats")
def get_alert_stats():
	"""Return aggregate alert statistics for a given session/time window."""
	session_id = request.args.get("session_id") or get_current_session_id()
	hours = int(request.args.get("hours", 24))
	stats = get_storage().get_stats(session_id=session_id, hours=hours)
	return jsonify(stats)


@api_analytics_bp.get("/api/alerts/timeline")
def get_alert_timeline():
	"""Return time-bucketed alert counts for charting."""
	session_id = request.args.get("session_id") or get_current_session_id()
	hours = int(request.args.get("hours", 24))
	interval = int(request.args.get("interval", 60))
	timeline = get_storage().get_timeline(session_id=session_id, hours=hours, interval_mins=interval)
	return jsonify(timeline)


@api_analytics_bp.get("/api/attack-types")
def get_attack_types():
	"""Return string-key JSON map for frontend consumption."""
	return jsonify({str(k): v for k, v in UNSW_ATTACK_TYPE_MAPPING.items()})


@api_analytics_bp.get("/api/alerts/by-type/<attack_type>")
def get_alerts_by_type(attack_type: str):
	"""Return alerts filtered by attack type."""
	session_id = request.args.get("session_id") or get_current_session_id()
	limit = int(request.args.get("limit", 100))
	alerts = get_storage().get_alerts(session_id=session_id, limit=limit, attack_type=attack_type)
	return jsonify({"session_id": session_id, "attack_type": attack_type, "count": len(alerts), "alerts": alerts})
