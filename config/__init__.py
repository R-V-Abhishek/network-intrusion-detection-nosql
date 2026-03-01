"""
config package — re-exports all public symbols so callers can do:

    from config import KAFKA_CONFIG, SPARK_CONFIG, UNSW_FEATURE_CONFIG, ...
    from config import get_scaler_path, get_model_and_scaler_paths
"""

from config.config import (  # noqa: F401
    KAFKA_CONFIG,
    SPARK_CONFIG,
    UNSW_FEATURE_CONFIG,
    UNSW_ATTACK_TYPE_MAPPING,
    MODEL_PATHS,
    STREAMING_CONFIG,
    ALERT_CONFIG,
    PRODUCER_CONFIG,
)

from config.scaler_paths import (  # noqa: F401
    MODEL_SCALER_MAP,
    get_scaler_path,
    get_model_and_scaler_paths,
)

__all__ = [
    # --- config.py ---
    "KAFKA_CONFIG",
    "SPARK_CONFIG",
    "UNSW_FEATURE_CONFIG",
    "UNSW_ATTACK_TYPE_MAPPING",
    "MODEL_PATHS",
    "STREAMING_CONFIG",
    "ALERT_CONFIG",
    "PRODUCER_CONFIG",
    # --- scaler_paths.py ---
    "MODEL_SCALER_MAP",
    "get_scaler_path",
    "get_model_and_scaler_paths",
]
