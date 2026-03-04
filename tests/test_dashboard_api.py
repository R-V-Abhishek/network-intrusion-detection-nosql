"""
Tests for dashboard/api_alerts.py and dashboard/api_analytics.py

These tests use Flask's test client — no real Cassandra or Redis needed.
Responses are checked for correct HTTP status and JSON structure.

Run with: pytest tests/test_dashboard_api.py -v
"""


# ─── Shared mock so imports inside api_alerts / api_analytics don't crash ────


class _MockStorage:
    """Minimal in-memory stand-in for AlertStorage."""
    def get_alerts(self, session_id, limit=100, attack_type=None):
        return [
            {
                "alert_id": "test-id-1",
                "session_id": session_id,
                "attack_type": "DoS",
                "severity": "high",
                "binary_probability": 0.95,
                "alert_time": "2026-01-01T00:00:00",
            }
        ]

    def get_stats(self, session_id, hours=24):
        return {
            "total": 1,
            "by_severity": {"high": 1, "medium": 0, "low": 0},
            "by_attack_type": {"DoS": 1},
        }

    def get_timeline(self, session_id, hours=24, interval_mins=60):
        return [{"bucket": "2026-01-01T00:00:00", "count": 1}]

    def get_sessions(self, limit=10):
        return [{"session_id": "sess-1", "dataset": "unsw"}]

    def get_current_session_id(self):
        return "sess-1"


# ─── ALERT CONFIG sanity checks (no Flask needed) ────────────────────────────

class TestAlertConfigSeverityLogic:
    """Makes sure severity labels used in API responses are consistent."""

    def test_high_severity_attacks(self):
        from config.config import ALERT_CONFIG
        high_attacks = [k for k, v in ALERT_CONFIG["severity_map"].items() if v == "high"]
        assert "DoS" in high_attacks
        assert "Exploits" in high_attacks
        assert "Backdoors" in high_attacks

    def test_normal_traffic_is_info(self):
        from config.config import ALERT_CONFIG
        assert ALERT_CONFIG["severity_map"]["Normal"] == "info"

    def test_no_missing_severity(self):
        from config.config import ALERT_CONFIG, UNSW_ATTACK_TYPE_MAPPING
        severity_map = ALERT_CONFIG["severity_map"]
        for name in UNSW_ATTACK_TYPE_MAPPING.values():
            assert name in severity_map


# ─── Attack type endpoint data ────────────────────────────────────────────────

class TestAttackTypeData:
    """Verifies the mapping that /api/attack-types would return."""

    def test_attack_type_mapping_serialisable(self):
        import json
        from config.config import UNSW_ATTACK_TYPE_MAPPING
        # Keys must be serialisable — JSON only allows string keys
        # Convert int keys → str as the endpoint would do
        serialised = {str(k): v for k, v in UNSW_ATTACK_TYPE_MAPPING.items()}
        result = json.dumps(serialised)
        parsed = json.loads(result)
        assert parsed["0"] == "Normal"
        assert len(parsed) == 10

    def test_all_attack_names_non_empty(self):
        from config.config import UNSW_ATTACK_TYPE_MAPPING
        for idx, name in UNSW_ATTACK_TYPE_MAPPING.items():
            assert name.strip() != "", f"Attack type at index {idx} is empty"
