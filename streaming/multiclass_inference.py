"""
Multiclass inference module for UNSW-NB15 streaming pipeline.

Loads the trained RandomForest multiclass classifier and applies attack
category classification to rows already flagged as attacks by binary inference.
"""


def load_multiclass_model(model_path):
    """Load the multiclass RandomForest classifier from disk."""
    pass


def apply_multiclass_inference(df, model, label_mapping):
    """
    Apply multiclass inference to a Spark DataFrame.

    Only runs on rows where binary_prediction == 1.
    Adds columns: attack_cat_id, attack_type (string), attack_confidence.
    """
    pass
