"""Unit tests for AlertStorage in-memory fallback path."""

from __future__ import annotations

from datetime import datetime, timedelta

from dashboard.storage import AlertStorage


def _make_alert(ts: datetime, attack_type: str = "DoS", severity: str = "high") -> dict:
    return {
        "alert_time": ts.isoformat(),
        "attack_type": attack_type,
        "severity": severity,
        "src_ip": "10.0.0.1",
        "dst_ip": "10.0.0.2",
        "src_port": 1234,
        "dst_port": 80,
        "protocol": "tcp",
        "binary_prediction": 1,
        "binary_probability": 0.9,
        "attack_confidence": 0.8,
        "sbytes": 100,
        "dbytes": 200,
        "rate": 1.5,
    }


def test_inmemory_store_get_stats_timeline_delete():
    storage = AlertStorage()
    session_id = "sess-1"
    storage.register_session(session_id, dataset="unsw")

    now = datetime.utcnow()
    older = now - timedelta(minutes=5)
    alerts = [_make_alert(older), _make_alert(now)]

    ids = storage.store_alerts(alerts, session_id=session_id)
    assert len(ids) == 2

    got = storage.get_alerts(session_id=session_id, limit=10)
    assert len(got) == 2
    assert got[0]["alert_time"] == alerts[1]["alert_time"]

    stats = storage.get_stats(session_id=session_id, hours=1)
    assert stats["total"] == 2
    assert stats["by_severity"]["high"] == 2
    assert stats["by_attack_type"]["DoS"] == 2

    timeline = storage.get_timeline(session_id=session_id, hours=1, interval_mins=60)
    assert sum(bucket["count"] for bucket in timeline) == 2

    result = storage.delete_session(session_id)
    assert result["session_removed"] is True
    assert result["removed_alerts"] == 2


def test_inmemory_delete_all_sessions():
    storage = AlertStorage()

    storage.register_session("sess-1", dataset="unsw")
    storage.register_session("sess-2", dataset="unsw")

    now = datetime.utcnow()
    storage.store_alerts([_make_alert(now)], session_id="sess-1")
    storage.store_alerts([_make_alert(now)], session_id="sess-2")

    result = storage.delete_all_sessions()
    assert result["removed_sessions"] == 2
    assert result["removed_alerts"] == 2

    assert storage.get_sessions(limit=10) == []
    assert storage.get_alerts(session_id="sess-1", limit=10) == []
    assert storage.get_alerts(session_id="sess-2", limit=10) == []
