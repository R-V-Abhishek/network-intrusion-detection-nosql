"""
Central configuration for the UNSW-NB15 Network Intrusion Detection pipeline.

All modules should import their constants from here.
Do NOT hard-code paths, topic names, or model settings elsewhere.
"""

import os

# ---------------------------------------------------------------------------
# Kafka
# ---------------------------------------------------------------------------
KAFKA_CONFIG = {
    "bootstrap_servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
    "topic": os.getenv("KAFKA_TOPIC", "nids-unsw"),
    "group_id": "nids-consumer-group",
    "auto_offset_reset": "latest",
    "enable_auto_commit": True,
    "producer_topic": "nids-unsw",
    "alert_topic": "nids-alerts",
}

# ---------------------------------------------------------------------------
# Spark
# ---------------------------------------------------------------------------
SPARK_CONFIG = {
    "app_name": "NIDS-UNSW-NB15",
    "master": os.getenv("SPARK_MASTER", "local[*]"),
    "executor_memory": "2g",
    "driver_memory": "2g",
    "packages": (
        "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0,"
        "com.datastax.spark:spark-cassandra-connector_2.12:3.4.1"
    ),
    "cassandra_host": os.getenv("CASSANDRA_HOST", "localhost"),
    "shuffle_partitions": "8",
}

# ---------------------------------------------------------------------------
# UNSW-NB15 feature configuration
# ---------------------------------------------------------------------------
UNSW_FEATURE_CONFIG = {
    "numeric_features": [
        "dur", "spkts", "dpkts", "sbytes", "dbytes", "rate",
        "sttl", "dttl", "sload", "dload", "sloss", "dloss",
        "sinpkt", "dinpkt", "sjit", "djit",
        "swin", "stcpb", "dtcpb", "dwin",
        "tcprtt", "synack", "ackdat",
        "smean", "dmean", "trans_depth", "response_body_len",
        "ct_srv_src", "ct_state_ttl", "ct_dst_ltm",
        "ct_src_dport_ltm", "ct_dst_sport_ltm", "ct_dst_src_ltm",
        "is_ftp_login", "ct_ftp_cmd", "ct_flw_http_mthd",
        "ct_src_ltm", "ct_srv_dst", "is_sm_ips_ports",
    ],
    "categorical_features": ["proto", "service", "state"],
    "label_col": "label",
    "attack_cat_col": "attack_cat",
    "attack_cat_id_col": "attack_cat_id",
    "drop_cols": ["id"],
    "feature_vector_col": "features_vec",
    "scaled_feature_col": "scaled_features",
}

# ---------------------------------------------------------------------------
# Attack category mapping  (int → string)
# Alphabetical order (Normal hard-coded to 0, rest 1–9 alphabetically)
# Generated deterministically in label_harmonization.ipynb
# ---------------------------------------------------------------------------
UNSW_ATTACK_TYPE_MAPPING = {
    0: "Normal",
    1: "Fuzzers",
    2: "Analysis",
    3: "Backdoors",
    4: "DoS",
    5: "Exploits",
    6: "Generic",
    7: "Reconnaissance",
    8: "Shellcode",
    9: "Worms",
}

# ---------------------------------------------------------------------------
# Model paths
# ---------------------------------------------------------------------------
_MODELS_BASE = os.getenv("MODELS_DIR", "models")

MODEL_PATHS = {
    # Binary classifier (Person 1 owns)
    "unsw_gbt_binary": os.path.join(_MODELS_BASE, "unsw_gbt_binary_classifier"),
    # Multiclass classifier (Person 2 owns)
    "unsw_multiclass": os.path.join(_MODELS_BASE, "unsw_rf_multiclass_classifier"),
    # Shared scaler (Person 1 trains, Person 2 reuses)
    "unsw_nb15_scaler": os.path.join(_MODELS_BASE, "unsw_nb15_scaler"),
    # Training results JSON
    "training_results": os.path.join(_MODELS_BASE, "unsw_training_results.json"),
    # Label mapping JSON (Person 2 generates)
    "label_mapping": os.path.join(_MODELS_BASE, "unsw_label_mapping.json"),
}

# ---------------------------------------------------------------------------
# Streaming
# ---------------------------------------------------------------------------
STREAMING_CONFIG = {
    "trigger_interval": "5 seconds",
    "watermark_delay": "10 seconds",
    "output_mode": "append",
    "checkpoint_dir": os.getenv("CHECKPOINT_DIR", "/tmp/nids_checkpoints"),
    "batch_size": 500,
}

# ---------------------------------------------------------------------------
# Alert rules
# ---------------------------------------------------------------------------
ALERT_CONFIG = {
    "severity_map": {
        # attack_type → severity level (high / medium / low)
        "DoS": "high",
        "Exploits": "high",
        "Backdoors": "high",
        "Shellcode": "high",
        "Worms": "high",
        "Generic": "medium",
        "Fuzzers": "medium",
        "Reconnaissance": "medium",
        "Analysis": "low",
        "Normal": "info",
    },
    "high_confidence_threshold": 0.80,
    "redis_key_recent": "nids:recent_alerts",
    "redis_channel": "nids:alerts",
    "redis_max_recent": 1000,  # max entries kept in the sorted set
    "alert_ttl_hours": 72,
}

# ---------------------------------------------------------------------------
# Kafka producer (used by kafka_producer.py)
# ---------------------------------------------------------------------------
PRODUCER_CONFIG = {
    "bootstrap_servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
    "topic": KAFKA_CONFIG["topic"],
    "data_sources": {
        "unsw": {
            "csv_paths": [
                "data/UNSW-NB15/UNSW-NB15_1.csv",
                "data/UNSW-NB15/UNSW-NB15_2.csv",
                "data/UNSW-NB15/UNSW-NB15_3.csv",
                "data/UNSW-NB15/UNSW-NB15_4.csv",
            ],
            "sample_csv": "data/UNSW-NB15/sample.csv",
        }
    },
    "default_rate": 500,   # rows per second
    "send_timeout_ms": 5000,
}
