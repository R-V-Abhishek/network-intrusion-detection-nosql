"""
Multiclass inference module for UNSW-NB15 streaming pipeline.

Loads the trained RandomForest multiclass classifier and applies attack
category classification to rows already flagged as attacks by binary inference.
"""

from typing import Dict

from pyspark.ml.classification import RandomForestClassificationModel
from pyspark.ml.functions import array_to_vector, vector_to_array
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, IntegerType, StringType


# Frequency-ranked label encoding fallback derived from sample UNSW-NB15 rows.
# Unknown values intentionally map to 0.0 so inference remains stable.
_CATEGORICAL_FALLBACK_ENCODING = {
    "proto": {
        "tcp": 1,
        "udp": 2,
        "unas": 3,
        "arp": 4,
    },
    "service": {
        "-": 1,
        "dns": 2,
        "http": 3,
        "ftp": 4,
        "ftp-data": 5,
        "smtp": 6,
        "ssh": 7,
    },
    "state": {
        "FIN": 1,
        "INT": 2,
        "CON": 3,
        "REQ": 4,
    },
}


def load_multiclass_model(model_path):
    """Load the multiclass RandomForest classifier from disk."""
    return RandomForestClassificationModel.load(model_path)


def _normalize_label_mapping(label_mapping: dict) -> Dict[int, str]:
    """Return a stable attack-id -> attack-name mapping from supported JSON layouts."""
    if not isinstance(label_mapping, dict):
        return {}

    if isinstance(label_mapping.get("reverse_mapping"), dict):
        source = label_mapping["reverse_mapping"]
        return {int(k): str(v) for k, v in source.items()}

    if isinstance(label_mapping.get("attack_mapping"), dict):
        source = label_mapping["attack_mapping"]
        return {int(v): str(k) for k, v in source.items()}

    # Fallback for plain {"0": "Normal", ...} shape.
    normalized: Dict[int, str] = {}
    for k, v in label_mapping.items():
        try:
            normalized[int(k)] = str(v)
        except (TypeError, ValueError):
            continue
    return normalized


def _encode_categorical_column(df: DataFrame, col_name: str, out_col: str) -> DataFrame:
    """Encode a categorical column using a small fallback label mapping."""
    mapping = _CATEGORICAL_FALLBACK_ENCODING.get(col_name, {})
    if col_name not in df.columns or not mapping:
        return df.withColumn(out_col, F.lit(0.0).cast(DoubleType()))

    map_expr = F.create_map([F.lit(x) for kv in mapping.items() for x in kv])
    return df.withColumn(
        out_col,
        F.coalesce(map_expr[F.col(col_name)], F.lit(0.0)).cast(DoubleType()),
    )


def _ensure_multiclass_features(df: DataFrame, model: RandomForestClassificationModel) -> DataFrame:
    """
    Ensure model.featuresCol exists and has the expected dimensionality.

    The binary stage produces a 39-feature numeric vector (`features_vec`). If
    the multiclass model expects more (e.g., 42), append fallback-encoded
    categorical slots for proto/service/state and pad any remaining slots with 0.
    """
    feature_col = model.getFeaturesCol()

    if feature_col in df.columns:
        return df

    if "features_vec" not in df.columns:
        return df

    expected_features = int(getattr(model, "numFeatures", 0) or 0)
    if expected_features <= 0:
        return df.withColumn(feature_col, F.col("features_vec"))

    base_feature_count = 39
    if expected_features <= base_feature_count:
        return df.withColumn(feature_col, F.col("features_vec"))

    df = _encode_categorical_column(df, "proto", "_mc_proto_idx")
    df = _encode_categorical_column(df, "service", "_mc_service_idx")
    df = _encode_categorical_column(df, "state", "_mc_state_idx")

    arr_col = vector_to_array(F.col("features_vec"))
    extra_needed = expected_features - base_feature_count

    cat_slots = [
        F.col("_mc_proto_idx"),
        F.col("_mc_service_idx"),
        F.col("_mc_state_idx"),
    ]
    if extra_needed > 0:
        arr_col = F.concat(arr_col, F.array(*cat_slots[: min(extra_needed, 3)]))

    if extra_needed > 3:
        arr_col = F.concat(arr_col, F.array_repeat(F.lit(0.0), extra_needed - 3))

    df = df.withColumn(feature_col, array_to_vector(arr_col))
    return df.drop("_mc_proto_idx", "_mc_service_idx", "_mc_state_idx")


def apply_multiclass_inference(df, model, label_mapping, include_normal_rows: bool = True):
    """
    Apply multiclass inference to a Spark DataFrame.

    Only runs on rows where binary_prediction == 1.
    Adds columns: attack_cat_id, attack_type (string), attack_confidence.

    Parameters
    ----------
    include_normal_rows : bool
        If True (default), returns all rows by unioning multiclass predictions
        for attack rows with passthrough normal rows. If False, returns only
        rows where binary_prediction == 1.
    """
    mapping = _normalize_label_mapping(label_mapping)

    # Ensure we have a valid feature column for model.transform.
    df = _ensure_multiclass_features(df, model)

    attacks_df = df.filter(F.col("binary_prediction") == 1)
    normal_df = df.filter(F.col("binary_prediction") != 1)

    predicted = model.transform(attacks_df)
    predicted = predicted.withColumn("attack_cat_id", F.col("prediction").cast(IntegerType()))

    id_to_type_expr = F.create_map([F.lit(x) for kv in mapping.items() for x in kv])
    predicted = predicted.withColumn(
        "attack_type",
        F.coalesce(id_to_type_expr[F.col("attack_cat_id")], F.lit("Unknown")),
    )

    predicted = predicted.withColumn("probability_arr", vector_to_array("probability"))
    predicted = predicted.withColumn(
        "attack_confidence",
        F.coalesce(F.col("probability_arr")[F.col("attack_cat_id")], F.lit(0.0)).cast(DoubleType()),
    ).drop("probability_arr")

    if not include_normal_rows:
        return predicted

    normal_cols = [c for c in predicted.columns if c not in normal_df.columns]
    for col_name in normal_cols:
        if col_name == "attack_cat_id":
            normal_df = normal_df.withColumn(col_name, F.lit(0).cast(IntegerType()))
        elif col_name == "attack_type":
            normal_df = normal_df.withColumn(col_name, F.lit("Normal").cast(StringType()))
        elif col_name == "attack_confidence":
            normal_df = normal_df.withColumn(col_name, F.lit(0.0).cast(DoubleType()))
        else:
            normal_df = normal_df.withColumn(col_name, F.lit(None))

    return predicted.unionByName(normal_df, allowMissingColumns=True)
