"""
Tests for config/config.py

These tests do NOT need Kafka, Spark, Cassandra, or Redis running.
They just verify that the config values are correct types and sensible values.
Run with: pytest tests/test_config.py -v
"""

import pytest
from config.config import (
    KAFKA_CONFIG,
    SPARK_CONFIG,
    UNSW_FEATURE_CONFIG,
    UNSW_ATTACK_TYPE_MAPPING,
    MODEL_PATHS,
    STREAMING_CONFIG,
    ALERT_CONFIG,
    PRODUCER_CONFIG,
)


# ─── KAFKA CONFIG ────────────────────────────────────────────────────────────

class TestKafkaConfig:
    def test_has_required_keys(self):
        required = {"bootstrap_servers", "topic", "group_id", "auto_offset_reset"}
        assert required.issubset(KAFKA_CONFIG.keys()), \
            f"Missing keys: {required - KAFKA_CONFIG.keys()}"

    def test_topic_is_string(self):
        assert isinstance(KAFKA_CONFIG["topic"], str)
        assert len(KAFKA_CONFIG["topic"]) > 0

    def test_bootstrap_servers_not_empty(self):
        assert KAFKA_CONFIG["bootstrap_servers"] != ""


# ─── SPARK CONFIG ────────────────────────────────────────────────────────────

class TestSparkConfig:
    def test_has_required_keys(self):
        required = {"app_name", "master", "executor_memory", "driver_memory"}
        assert required.issubset(SPARK_CONFIG.keys())

    def test_app_name_is_string(self):
        assert isinstance(SPARK_CONFIG["app_name"], str)
        assert len(SPARK_CONFIG["app_name"]) > 0


# ─── FEATURE CONFIG ──────────────────────────────────────────────────────────

class TestUnswFeatureConfig:
    def test_numeric_features_count(self):
        """UNSW-NB15 must have exactly 39 numeric features — agreed on Day 1."""
        assert len(UNSW_FEATURE_CONFIG["numeric_features"]) == 39, (
            f"Expected 39 numeric features, got {len(UNSW_FEATURE_CONFIG['numeric_features'])}"
        )

    def test_no_duplicate_features(self):
        features = UNSW_FEATURE_CONFIG["numeric_features"]
        assert len(features) == len(set(features)), "Duplicate feature names found"

    def test_label_col_defined(self):
        assert UNSW_FEATURE_CONFIG["label_col"] == "label"

    def test_attack_cat_col_defined(self):
        assert UNSW_FEATURE_CONFIG["attack_cat_col"] == "attack_cat"

    def test_categorical_features_present(self):
        cats = UNSW_FEATURE_CONFIG["categorical_features"]
        assert "proto" in cats
        assert "service" in cats
        assert "state" in cats

    def test_known_features_present(self):
        """Spot-check a few critical UNSW-NB15 feature names."""
        features = UNSW_FEATURE_CONFIG["numeric_features"]
        for name in ["dur", "sbytes", "dbytes", "sttl", "dttl", "rate"]:
            assert name in features, f"Expected feature '{name}' not found"


# ─── ATTACK TYPE MAPPING ─────────────────────────────────────────────────────

class TestAttackTypeMapping:
    def test_has_10_classes(self):
        """UNSW-NB15 has 10 categories: Normal + 9 attack types."""
        assert len(UNSW_ATTACK_TYPE_MAPPING) == 10

    def test_normal_is_zero(self):
        assert UNSW_ATTACK_TYPE_MAPPING[0] == "Normal"

    def test_all_keys_are_ints(self):
        for key in UNSW_ATTACK_TYPE_MAPPING:
            assert isinstance(key, int), f"Key {key!r} is not an int"

    def test_all_values_are_strings(self):
        for val in UNSW_ATTACK_TYPE_MAPPING.values():
            assert isinstance(val, str) and len(val) > 0

    def test_expected_attack_types_present(self):
        values = set(UNSW_ATTACK_TYPE_MAPPING.values())
        expected = {"Normal", "DoS", "Exploits", "Fuzzers", "Generic",
                    "Reconnaissance", "Shellcode", "Worms", "Backdoors", "Analysis"}
        assert values == expected


# ─── MODEL PATHS ─────────────────────────────────────────────────────────────

class TestModelPaths:
    def test_has_required_model_keys(self):
        required = {"unsw_gbt_binary", "unsw_multiclass", "unsw_nb15_scaler",
                    "training_results", "label_mapping"}
        assert required.issubset(MODEL_PATHS.keys())

    def test_all_paths_are_strings(self):
        for key, path in MODEL_PATHS.items():
            assert isinstance(path, str), f"MODEL_PATHS['{key}'] is not a string"
            assert len(path) > 0


# ─── ALERT CONFIG ────────────────────────────────────────────────────────────

class TestAlertConfig:
    def test_severity_map_covers_all_attack_types(self):
        """Every attack type in UNSW_ATTACK_TYPE_MAPPING must have a severity."""
        severity_map = ALERT_CONFIG["severity_map"]
        for attack_type in UNSW_ATTACK_TYPE_MAPPING.values():
            assert attack_type in severity_map, \
                f"Attack type '{attack_type}' missing from ALERT_CONFIG severity_map"

    def test_severity_values_are_valid(self):
        valid = {"high", "medium", "low", "info"}
        for attack, sev in ALERT_CONFIG["severity_map"].items():
            assert sev in valid, f"'{attack}' has invalid severity '{sev}'"

    def test_confidence_threshold_in_range(self):
        threshold = ALERT_CONFIG["high_confidence_threshold"]
        assert 0.0 < threshold < 1.0, \
            f"Confidence threshold {threshold} must be between 0 and 1"

    def test_redis_keys_defined(self):
        assert "redis_key_recent" in ALERT_CONFIG
        assert "redis_channel" in ALERT_CONFIG


# ─── STREAMING CONFIG ────────────────────────────────────────────────────────

class TestStreamingConfig:
    def test_has_required_keys(self):
        required = {"trigger_interval", "watermark_delay", "output_mode",
                    "checkpoint_dir", "batch_size"}
        assert required.issubset(STREAMING_CONFIG.keys())

    def test_batch_size_is_positive_int(self):
        assert isinstance(STREAMING_CONFIG["batch_size"], int)
        assert STREAMING_CONFIG["batch_size"] > 0


# ─── PRODUCER CONFIG ─────────────────────────────────────────────────────────

class TestProducerConfig:
    def test_unsw_data_source_defined(self):
        assert "unsw" in PRODUCER_CONFIG["data_sources"]

    def test_unsw_has_csv_paths(self):
        csv_paths = PRODUCER_CONFIG["data_sources"]["unsw"]["csv_paths"]
        assert isinstance(csv_paths, list)
        assert len(csv_paths) == 4, "Expected 4 UNSW-NB15 CSV files"

    def test_default_rate_positive(self):
        assert PRODUCER_CONFIG["default_rate"] > 0
