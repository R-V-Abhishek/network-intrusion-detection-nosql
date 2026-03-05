"""Multiclass inference utilities for UNSW-NB15 attack classification."""

from __future__ import annotations

from typing import Dict

from pyspark.ml.classification import RandomForestClassificationModel
from pyspark.ml.functions import vector_to_array
from pyspark.sql import DataFrame
from pyspark.sql import functions as F

from config import UNSW_ATTACK_TYPE_MAPPING, UNSW_FEATURE_CONFIG


def load_multiclass_model(model_path: str) -> RandomForestClassificationModel:
    """Load a trained multiclass Spark ML model from disk."""
    return RandomForestClassificationModel.load(model_path)


def apply_multiclass_inference(
    df: DataFrame,
    model: RandomForestClassificationModel,
    label_mapping: Dict[int, str] | None = None,
) -> DataFrame:
    """Apply multiclass attack-type inference to attack rows only.

    This function scores only rows where ``binary_prediction == 1`` and returns
    the full input dataset with three additional columns:
    - ``attack_cat_id`` (int)
    - ``attack_type`` (string)
    - ``attack_confidence`` (double)
    """
    if label_mapping is None:
        label_mapping = UNSW_ATTACK_TYPE_MAPPING

    normalized_mapping = {int(k): str(v) for k, v in label_mapping.items()}
    feature_col = model.getFeaturesCol()
    probability_col = model.getProbabilityCol()
    prediction_col = model.getPredictionCol()

    if feature_col not in df.columns:
        fallback_scaled = UNSW_FEATURE_CONFIG.get("scaled_feature_col", "scaled_features")
        fallback_alt = "features_scaled"
        if fallback_scaled in df.columns:
            df = df.withColumnRenamed(fallback_scaled, feature_col)
        elif fallback_alt in df.columns:
            df = df.withColumnRenamed(fallback_alt, feature_col)
        else:
            raise ValueError(
                f"Expected features column '{feature_col}' not found in input DataFrame"
            )

    attack_only = df.filter(F.col("binary_prediction") == 1)
    non_attack = df.filter((F.col("binary_prediction") != 1) | F.col("binary_prediction").isNull())

    mapping_expr_args = []
    for key, value in sorted(normalized_mapping.items()):
        mapping_expr_args.extend([F.lit(int(key)), F.lit(value)])
    mapping_expr = F.create_map(*mapping_expr_args)

    scored_attack = model.transform(attack_only)
    if probability_col in scored_attack.columns:
        confidence_col = F.array_max(vector_to_array(F.col(probability_col))).cast("double")
    else:
        confidence_col = F.lit(None).cast("double")

    scored_attack = (
        scored_attack.withColumn("attack_cat_id", F.col(prediction_col).cast("int"))
        .withColumn("attack_type", mapping_expr[F.col("attack_cat_id")])
        .withColumn("attack_type", F.coalesce(F.col("attack_type"), F.lit("Unknown")))
        .withColumn("attack_confidence", confidence_col)
        .select(*df.columns, "attack_cat_id", "attack_type", "attack_confidence")
    )

    non_attack = (
        non_attack.withColumn("attack_cat_id", F.lit(None).cast("int"))
        .withColumn("attack_type", F.lit(None).cast("string"))
        .withColumn("attack_confidence", F.lit(None).cast("double"))
        .select(*df.columns, "attack_cat_id", "attack_type", "attack_confidence")
    )

    return scored_attack.unionByName(non_attack)
