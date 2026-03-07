"""
Flask Web Application for NIDS Dashboard

Main application with:
- Session management endpoints
- Health check API
- Blueprint registration for alerts and analytics
- Static file serving and templates
"""

import os
import sys
from flask import Flask, render_template, jsonify, request

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from alert_storage import (
    AlertStorage, 
    get_current_session_id, 
    set_current_session_id,
    start_new_session
)
from config.config import CASSANDRA_CONFIG, REDIS_CONFIG

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-prod')
app.config['JSON_SORT_KEYS'] = False

# Initialize storage (will be connected on first request)
storage = AlertStorage()


# ══════════════════════════════════════════════════════════════════════════
# ROUTES — Main Pages
# ══════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    """Render main dashboard page."""
    return render_template('dashboard.html')


@app.route('/alerts')
def alerts_page():
    """Render alerts list page."""
    return render_template('alerts.html')


@app.route('/analytics')
def analytics_page():
    """Render analytics page with charts."""
    return render_template('analytics.html')


@app.route('/settings')
def settings_page():
    """Render settings page for session management."""
    return render_template('settings.html')


# ══════════════════════════════════════════════════════════════════════════
# API ENDPOINTS — Health & System Status
# ══════════════════════════════════════════════════════════════════════════

@app.route('/api/health')
def health_check():
    """
    Health check endpoint - verifies Cassandra and Redis connectivity.
    
    Returns:
        JSON with status of each service
    """
    health_status = {
        "status": "healthy",
        "services": {}
    }
    
    # Check Cassandra
    try:
        if storage.cassandra_session is None:
            storage.connect()
        
        storage.cassandra_session.execute("SELECT now() FROM system.local")
        health_status["services"]["cassandra"] = {
            "status": "connected",
            "host": CASSANDRA_CONFIG["contact_points"][0],
            "port": CASSANDRA_CONFIG["port"],
            "keyspace": CASSANDRA_CONFIG["keyspace"]
        }
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["services"]["cassandra"] = {
            "status": "error",
            "error": str(e)
        }
    
    # Check Redis
    try:
        if storage.redis_client is None:
            storage.connect()
        
        storage.redis_client.ping()
        health_status["services"]["redis"] = {
            "status": "connected",
            "host": REDIS_CONFIG["host"],
            "port": REDIS_CONFIG["port"]
        }
    except Exception as e:
        health_status["status"] = "degraded"
        health_status["services"]["redis"] = {
            "status": "error",
            "error": str(e)
        }
    
    status_code = 200 if health_status["status"] == "healthy" else 503
    return jsonify(health_status), status_code


# ══════════════════════════════════════════════════════════════════════════
# API ENDPOINTS — Session Management
# ══════════════════════════════════════════════════════════════════════════

@app.route('/api/sessions', methods=['GET'])
def get_sessions():
    """
    Get list of all sessions.
    
    Returns:
        JSON array of sessions
    """
    try:
        if storage.cassandra_session is None:
            storage.connect()
        
        sessions = storage.get_sessions(limit=50)
        return jsonify({
            "success": True,
            "sessions": sessions,
            "count": len(sessions)
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/session/current', methods=['GET'])
def get_current_session():
    """
    Get the current active session ID.
    
    Returns:
        JSON with current session_id
    """
    try:
        session_id = get_current_session_id()
        return jsonify({
            "success": True,
            "session_id": session_id
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/session/set', methods=['POST'])
def set_session():
    """
    Set the current active session.
    
    Request body:
        {"session_id": "uuid-string"}
    
    Returns:
        JSON confirmation
    """
    try:
        data = request.get_json()
        session_id = data.get('session_id')
        
        if not session_id:
            return jsonify({
                "success": False,
                "error": "session_id is required"
            }), 400
        
        set_current_session_id(session_id)
        
        return jsonify({
            "success": True,
            "session_id": session_id,
            "message": f"Current session set to {session_id}"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/session/new', methods=['POST'])
def create_new_session():
    """
    Create a new session.
    
    Request body:
        {"dataset": "unsw"} (optional)
    
    Returns:
        JSON with new session_id
    """
    try:
        data = request.get_json() or {}
        dataset = data.get('dataset', 'unsw')
        
        session_id = start_new_session(dataset=dataset)
        
        return jsonify({
            "success": True,
            "session_id": session_id,
            "dataset": dataset,
            "message": "New session created"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/session/delete', methods=['DELETE'])
def delete_session():
    """
    Delete a session and all associated alerts.
    
    Request body:
        {"session_id": "uuid-string"}
    
    Returns:
        JSON confirmation
    """
    try:
        if storage.cassandra_session is None:
            storage.connect()
        
        data = request.get_json()
        session_id = data.get('session_id')
        
        if not session_id:
            return jsonify({
                "success": False,
                "error": "session_id is required"
            }), 400
        
        result = storage.delete_session(session_id)
        
        return jsonify({
            "success": True,
            **result
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/api/sessions/delete-all', methods=['DELETE'])
def delete_all_sessions():
    """
    Delete all sessions and alerts (WARNING: irreversible).
    
    Returns:
        JSON confirmation
    """
    try:
        if storage.cassandra_session is None:
            storage.connect()
        
        result = storage.delete_all_sessions()
        
        return jsonify({
            "success": True,
            **result
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ══════════════════════════════════════════════════════════════════════════
# BLUEPRINT REGISTRATION
# ══════════════════════════════════════════════════════════════════════════

# These blueprints will be created by Person 1 and Person 2
# For now, we'll register them if they exist, otherwise skip

try:
    from dashboard.api_alerts import alerts_bp
    app.register_blueprint(alerts_bp, url_prefix='/api/alerts')
    print("[App] Registered alerts blueprint")
except ImportError:
    print("[App] Alerts blueprint not yet implemented (Person 1)")

try:
    from dashboard.api_analytics import analytics_bp
    app.register_blueprint(analytics_bp, url_prefix='/api/analytics')
    print("[App] Registered analytics blueprint")
except ImportError:
    print("[App] Analytics blueprint not yet implemented (Person 2)")


# ══════════════════════════════════════════════════════════════════════════
# APPLICATION INITIALIZATION
# ══════════════════════════════════════════════════════════════════════════

@app.before_request
def ensure_storage_connected():
    """Ensure storage is connected before handling requests."""
    if storage.cassandra_session is None or storage.redis_client is None:
        storage.connect()


@app.teardown_appcontext
def shutdown_session(exception=None):
    """Clean up resources on app shutdown."""
    pass  # Storage cleanup handled by signal handlers


# ══════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    """
    Run Flask development server.
    
    Usage:
        python dashboard/app.py
    """
    print("\n" + "=" * 80)
    print("NIDS Dashboard Server Starting")
    print("=" * 80)
    print(f"Dashboard:       http://localhost:5000")
    print(f"Alerts Page:     http://localhost:5000/alerts")
    print(f"Analytics Page:  http://localhost:5000/analytics")
    print(f"Settings Page:   http://localhost:5000/settings")
    print(f"Health Check:    http://localhost:5000/api/health")
    print("=" * 80 + "\n")
    
    # Run Flask app
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True,
        use_reloader=True
    )
