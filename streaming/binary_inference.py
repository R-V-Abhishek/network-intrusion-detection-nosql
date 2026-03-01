"""
Binary inference module for UNSW-NB15 streaming pipeline.

Loads the trained GBT binary classifier and StandardScaler, assembles features,
and applies binary (normal/attack) prediction to incoming Spark DataFrames.
"""


def load_binary_model(model_path, scaler_path):
    """Load the binary GBT classifier and StandardScaler from disk."""
    pass


def assemble_features(df, feature_cols):
    """Assemble feature columns into a single vector column using VectorAssembler."""
    pass


def apply_binary_inference(df, model, scaler):
    """
    Apply binary inference to a Spark DataFrame.

    Returns df with added columns: features_vec, binary_prediction, binary_probability.
    """
    pass
