"""Integration smoke tests for storage backends.

These tests are opt-in and require Docker services from docker-compose.ci.yml.
Enable them by setting NIDS_RUN_INTEGRATION=1.
"""

from __future__ import annotations

import os

import pytest

from dashboard.storage import AlertStorage


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("NIDS_RUN_INTEGRATION", "0") != "1",
        reason="Set NIDS_RUN_INTEGRATION=1 to run integration tests.",
    ),
]


def test_storage_connects_to_at_least_one_backend() -> None:
    storage = AlertStorage()
    try:
        assert storage.connect() is True
        diag = storage.diagnostics()
        assert diag["redis_connected"] or diag["cassandra_connected"]
    finally:
        storage.close()


def test_store_and_fetch_alert_round_trip() -> None:
    storage = AlertStorage()
    session_id = "ci-smoke-session"
    alert = {
        "attack_type": "DoS",
        "severity": "high",
        "src_ip": "10.0.0.1",
        "dst_ip": "10.0.0.2",
        "binary_prediction": 1,
        "binary_probability": 0.99,
        "attack_confidence": 0.95,
        "protocol": "tcp",
    }

    try:
        storage.connect()
        storage.register_session(session_id, dataset="unsw")

        ids = storage.store_alerts([alert], session_id=session_id)
        assert len(ids) == 1

        rows = storage.get_alerts(session_id=session_id, limit=20)
        assert any(row.get("alert_id") == ids[0] for row in rows)
    finally:
        storage.delete_session(session_id)
        storage.close()
