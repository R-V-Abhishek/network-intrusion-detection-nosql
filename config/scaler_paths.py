"""
Scaler path helpers.

Maps each model to its associated fitted scaler so callers don't need to
know the internal model → scaler relationship.
"""

from config.config import MODEL_PATHS

# Every model that requires a pre-fitted scaler at inference time
# maps model_key → scaler_key (both referencing MODEL_PATHS)
MODEL_SCALER_MAP: dict[str, str] = {
    "unsw_gbt_binary": "unsw_nb15_scaler",
    "unsw_multiclass": "unsw_nb15_scaler",
}


def get_scaler_path(model_key: str) -> str:
    """Return the filesystem path of the scaler associated with *model_key*.

    Args:
        model_key: A key that exists in MODEL_PATHS, e.g. "unsw_gbt_binary".

    Returns:
        Absolute (or relative) path string to the saved scaler directory.

    Raises:
        KeyError: If no scaler is registered for *model_key*.
    """
    scaler_key = MODEL_SCALER_MAP[model_key]
    return MODEL_PATHS[scaler_key]


def get_model_and_scaler_paths(model_key: str) -> tuple[str, str]:
    """Convenience helper — returns (model_path, scaler_path) as a tuple.

    Args:
        model_key: A key that exists in MODEL_PATHS.

    Returns:
        Tuple of (model_path, scaler_path).
    """
    return MODEL_PATHS[model_key], get_scaler_path(model_key)
