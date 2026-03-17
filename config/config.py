"""
Centralized Configuration for NIDS Project

This config file defines all settings needed for:
- Kafka message broker
- Spark streaming
- UNSW-NB15 dataset features
- Machine learning model paths
- Alert severity mapping
- Redis caching
"""

import os

# ────────────────────────────────────────────────────────────────────────────
# KAFKA CONFIGURATION
# ────────────────────────────────────────────────────────────────────────────

KAFKA_CONFIG = {
    "bootstrap_servers": os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092"),
    "topic": "network-traffic",
    "group_id": "nids-consumer-group",
    "auto_offset_reset": "latest",
}

# ────────────────────────────────────────────────────────────────────────────
# SPARK CONFIGURATION
# ────────────────────────────────────────────────────────────────────────────

SPARK_CONFIG = {
    "app_name": "NIDS-Streaming-Pipeline",
    "master": "local[*]",
    "executor_memory": "2g",
    "driver_memory": "2g",
    "log_level": "WARN",
}

# ────────────────────────────────────────────────────────────────────────────
# UNSW-NB15 DATASET FEATURE CONFIGURATION
# ────────────────────────────────────────────────────────────────────────────

UNSW_FEATURE_CONFIG = {
    # Exactly 39 numeric features from UNSW-NB15 dataset
    "numeric_features": [
        "dur", "spkts", "dpkts", "sbytes", "dbytes",
        "rate", "sttl", "dttl", "sload", "dload",
        "sloss", "dloss", "sinpkt", "dinpkt", "sjit",
        "djit", "swin", "stcpb", "dtcpb", "dwin",
        "tcprtt", "synack", "ackdat", "smean", "dmean",
        "trans_depth", "response_body_len", "ct_srv_src", "ct_state_ttl", "ct_dst_ltm",
        "ct_src_dport_ltm", "ct_dst_sport_ltm", "ct_dst_src_ltm", "is_ftp_login", "ct_ftp_cmd",
        "ct_flw_http_mthd", "ct_src_ltm", "ct_srv_dst", "is_sm_ips_ports"
    ],

    # Categorical features
    "categorical_features": ["proto", "service", "state"],

    # Target columns
    "label_col": "label",           # Binary: 0 = Normal, 1 = Attack
    "attack_cat_col": "attack_cat",  # Multiclass: specific attack type
}

# ────────────────────────────────────────────────────────────────────────────
# UNSW-NB15 ATTACK TYPE MAPPING (Multiclass Labels)
# ────────────────────────────────────────────────────────────────────────────

UNSW_ATTACK_TYPE_MAPPING = {
    0: "Normal",
    1: "DoS",
    2: "Exploits",
    3: "Fuzzers",
    4: "Generic",
    5: "Reconnaissance",
    6: "Shellcode",
    7: "Worms",
    8: "Backdoors",
    9: "Analysis",
}

# ────────────────────────────────────────────────────────────────────────────
# MODEL PATHS
# ────────────────────────────────────────────────────────────────────────────

MODEL_PATHS = {
    "unsw_gbt_binary": "models/unsw_gbt_binary_classifier",
    "unsw_multiclass": "models/unsw_rf_multiclass_classifier",
    "unsw_nb15_scaler": "models/unsw_nb15_scaler",
    "training_results": "models/unsw_training_results.json",
    "label_mapping": "models/unsw_label_mapping.json",
}

# ────────────────────────────────────────────────────────────────────────────
# ALERT CONFIGURATION
# ────────────────────────────────────────────────────────────────────────────

ALERT_CONFIG = {
    # Severity mapping for each attack type
    "severity_map": {
        "Normal": "info",
        "DoS": "high",
        "Exploits": "high",
        "Fuzzers": "medium",
        "Generic": "medium",
        "Reconnaissance": "low",
        "Shellcode": "high",
        "Worms": "medium",
        "Backdoors": "high",
        "Analysis": "low",
    },

    # Confidence threshold for high-confidence alerts
    "high_confidence_threshold": 0.8,

    # Redis keys for storing alerts
    "redis_key_recent": "recent_alerts",
    "redis_channel": "alert_notifications",
}

# ────────────────────────────────────────────────────────────────────────────
# STREAMING CONFIGURATION
# ────────────────────────────────────────────────────────────────────────────

STREAMING_CONFIG = {
    "trigger_interval": os.getenv("STREAMING_TRIGGER_INTERVAL", "30 seconds"),
    "watermark_delay": "30 seconds",
    "output_mode": "append",
    "checkpoint_dir": "/tmp/spark_checkpoints",
    "batch_size": 1000,
    "max_offsets_per_trigger": int(os.getenv("STREAMING_MAX_OFFSETS_PER_TRIGGER", "100")),
}

# ────────────────────────────────────────────────────────────────────────────
# DATA PRODUCER CONFIGURATION
# ────────────────────────────────────────────────────────────────────────────

PRODUCER_CONFIG = {
    "data_sources": {
        "unsw": {
            "csv_paths": [
                "data/UNSW-NB15/UNSW-NB15_1.csv",
                "data/UNSW-NB15/UNSW-NB15_2.csv",
                "data/UNSW-NB15/UNSW-NB15_3.csv",
                "data/UNSW-NB15/UNSW-NB15_4.csv",
            ],
            "sampling_rate": 0.1,  # Use 10% of data for testing
        }
    },
    "default_rate": 100,  # Records per second
    "max_records": None,   # None = infinite stream
}

# ────────────────────────────────────────────────────────────────────────────
# CASSANDRA CONFIGURATION
# ────────────────────────────────────────────────────────────────────────────

CASSANDRA_CONFIG = {
    "contact_points": [os.getenv("CASSANDRA_HOST", "localhost")],
    "port": int(os.getenv("CASSANDRA_PORT", "9042")),
    "keyspace": "nids",
    "tables": {
        "alerts": "alerts",
        "traffic_stats": "traffic_stats",
    },
}

# ────────────────────────────────────────────────────────────────────────────
# REDIS CONFIGURATION
# ────────────────────────────────────────────────────────────────────────────

REDIS_CONFIG = {
    "host": os.getenv("REDIS_HOST", "localhost"),
    "port": int(os.getenv("REDIS_PORT", "6379")),
    "db": 0,
    "decode_responses": True,
    "socket_connect_timeout": float(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", "3")),
    "socket_timeout": float(os.getenv("REDIS_SOCKET_TIMEOUT", "8")),
}

# ────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT-SPECIFIC OVERRIDES
# ────────────────────────────────────────────────────────────────────────────

# Check if we're in stub/test mode (no real models needed)
STUB_MODELS = os.getenv("STUB_MODELS", "false").lower() in ("true", "1", "yes")

if STUB_MODELS:
    print("[CONFIG] Running in STUB_MODELS mode — ML models will be mocked")
