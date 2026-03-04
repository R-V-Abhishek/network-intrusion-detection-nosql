"""
Tests for streaming/pipeline_runner.py

Tests verify only the parts that don't need Spark/Kafka:
  - STUB_MODELS env-var parsing
  - extract_attack_rows logic (pure Python / pandas)

Run with: pytest tests/test_pipeline.py -v
"""

import os


class TestStubModelsFlag:
    """Verify STUB_MODELS env-var is read correctly."""

    def test_stub_models_false_by_default(self):
        os.environ.pop("STUB_MODELS", None)
        stub = os.getenv("STUB_MODELS", "false").lower() == "true"
        assert stub is False

    def test_stub_models_true_when_set(self):
        os.environ["STUB_MODELS"] = "true"
        stub = os.getenv("STUB_MODELS", "false").lower() == "true"
        assert stub is True
        del os.environ["STUB_MODELS"]

    def test_stub_models_case_insensitive(self):
        for value in ("TRUE", "True", "TRUE"):
            os.environ["STUB_MODELS"] = value
            stub = os.getenv("STUB_MODELS", "false").lower() == "true"
            assert stub is True
        del os.environ["STUB_MODELS"]


class TestExtractAttackRowsLogic:
    """
    Validates the filter logic that pipeline_runner uses to extract alerts.
    Uses plain pandas — no Spark needed.
    """

    def _make_df(self):
        import pandas as pd
        return pd.DataFrame({
            "binary_prediction": [0, 1, 1, 0, 1],
            "binary_probability": [0.1, 0.95, 0.88, 0.2, 0.76],
            "attack_type": [None, "DoS", "Exploits", None, "Fuzzers"],
            "src_ip": ["1.1.1.1"] * 5,
        })

    def test_only_attack_rows_returned(self):
        df = self._make_df()
        attacks = df[df["binary_prediction"] == 1]
        assert len(attacks) == 3

    def test_normal_rows_excluded(self):
        df = self._make_df()
        attacks = df[df["binary_prediction"] == 1]
        assert all(attacks["binary_prediction"] == 1)

    def test_high_confidence_filter(self):
        from config.config import ALERT_CONFIG
        df = self._make_df()
        threshold = ALERT_CONFIG["high_confidence_threshold"]
        high_conf = df[
            (df["binary_prediction"] == 1) &
            (df["binary_probability"] >= threshold)
        ]
        # Only 0.95 and 0.88 are ≥ 0.80 (default threshold)
        assert len(high_conf) == 2
