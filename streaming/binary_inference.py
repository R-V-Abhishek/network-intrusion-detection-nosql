"""
Binary inference module for UNSW-NB15 streaming pipeline.

Loads the trained GBT binary classifier and StandardScaler, assembles features,
and applies binary (normal/attack) prediction to incoming Spark DataFrames.
"""

from typing import Tuple

from pyspark.ml.classification import GBTClassificationModel
from pyspark.ml.feature import StandardScalerModel, VectorAssembler
from pyspark.ml.functions import vector_to_array
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType

from config.config import UNSW_FEATURE_CONFIG


def load_binary_model(
    model_path: str, scaler_path: str
) -> Tuple[GBTClassificationModel, StandardScalerModel]:
    """
    Load the binary GBT classifier and StandardScaler from disk.

    Parameters
    ----------
    model_path : str
        Path to the saved GBTClassificationModel directory.
    scaler_path : str
        Path to the saved StandardScalerModel directory.

    Returns
    -------
    Tuple[GBTClassificationModel, StandardScalerModel]
        (binary_model, scaler_model)
    """
    binary_model = GBTClassificationModel.load(model_path)
    scaler_model = StandardScalerModel.load(scaler_path)
    return binary_model, scaler_model


def assemble_features(df: DataFrame, feature_cols: list) -> DataFrame:
    """
    Assemble feature columns into a single 'features_raw' vector column.

    Parameters
    ----------
    df : DataFrame
        Input Spark DataFrame.
    feature_cols : list
        Ordered list of numeric feature column names.

    Returns
    -------
    DataFrame
        DataFrame with an added 'features_raw' column.
    """
    # Build one select() expression per feature col so the query plan stays flat.
    # Calling withColumn() in a loop creates O(n) nested plan nodes which causes
    # Catalyst optimizer to hang (exponential cost) on wide feature sets.
    existing = set(df.columns)
    passthrough = [c for c in df.columns if c not in feature_cols]

    feature_exprs = []
    for col_name in feature_cols:
        if col_name in existing:
            expr = (
                F.when(F.col(col_name).isNull(), F.lit(0.0))
                .when(F.col(col_name) == float("inf"), F.lit(0.0))
                .when(F.col(col_name) == float("-inf"), F.lit(0.0))
                .otherwise(F.col(col_name).cast(DoubleType()))
                .alias(col_name)
            )
        else:
            expr = F.lit(0.0).cast(DoubleType()).alias(col_name)
        feature_exprs.append(expr)

    df = df.select(
        [F.col(c) for c in passthrough] + feature_exprs
    )

    assembler = VectorAssembler(
        inputCols=feature_cols,
        outputCol="features_raw",
        handleInvalid="keep",
    )
    return assembler.transform(df)


def apply_binary_inference(
    df: DataFrame,
    model: GBTClassificationModel,
    scaler: StandardScalerModel,
) -> DataFrame:
    """
    Apply binary inference to a Spark DataFrame.

    Adds columns:
        features_vec        — scaled feature vector used by the model
        binary_prediction   — 0.0 (Normal) or 1.0 (Attack)
        binary_probability  — confidence score for the positive (Attack) class

    Parameters
    ----------
    df : DataFrame
        Input Spark DataFrame that already contains the raw numeric feature cols,
        OR has been passed through assemble_features() already. If 'features_raw'
        is absent the function calls assemble_features() internally using the
        scaler's expected input column list.
    model : GBTClassificationModel
        Trained GBT binary classifier (featuresCol='features_scaled').
    scaler : StandardScalerModel
        Fitted StandardScaler (inputCol='features_raw', outputCol='features_scaled').

    Returns
    -------
    DataFrame
        Original DataFrame with three new columns added.
    """
    # Assemble raw feature vector if not already present
    if "features_raw" not in df.columns:
        # Use the exact training feature order expected by the scaler/model.
        feature_cols = UNSW_FEATURE_CONFIG["numeric_features"]
        df = assemble_features(df, feature_cols)

    # Scale features
    df = scaler.transform(df).withColumnRenamed("features_scaled", "features_vec")

    # Run GBT inference (expects features column named 'features_scaled')
    # Temporarily alias so the model's featuresCol matches
    df = df.withColumnRenamed("features_vec", "features_scaled")
    df = model.transform(df)
    df = df.withColumnRenamed("features_scaled", "features_vec")

    # Rename model output columns to pipeline-standard names
    df = df.withColumnRenamed("prediction", "binary_prediction")

    # Extract probability of the positive (Attack) class from the probability vector.
    # Uses vector_to_array (native Spark, no Python UDF) to avoid Python worker crashes
    # caused by WinError 10038 on Windows when using F.udf with socket-based workers.
    df = df.withColumn("probability_arr", vector_to_array(F.col("probability")))
    df = df.withColumn(
        "binary_probability",
        F.coalesce(F.col("probability_arr")[1], F.lit(0.0)).cast(DoubleType()),
    )
    df = df.drop("probability", "rawPrediction", "probability_arr")

    return df


# ---------------------------------------------------------------------------
# Standalone smoke-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import os
    import sys
    from pathlib import Path

    # Allow running from repo root or scripts/ dir
    REPO_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(REPO_ROOT / "src"))

    from pyspark.sql import SparkSession

    MODEL_DIR = REPO_ROOT / "models"
    SAMPLE_PATH = str(REPO_ROOT / "data" / "UNSW-NB15" / "sample.csv")
    MODEL_PATH = str(MODEL_DIR / "unsw_gbt_binary_classifier")
    SCALER_PATH = str(MODEL_DIR / "unsw_nb15_scaler")

    if not Path(MODEL_PATH).exists():
        print(f"[smoke-test] Model not found at {MODEL_PATH}")
        print("  Run the training notebook first to produce model files.")
        sys.exit(1)

    spark = (
        SparkSession.builder.appName("binary_inference_test")
        .master("local[*]")
        .config("spark.driver.memory", "2g")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("ERROR")

    print(f"Loading sample from: {SAMPLE_PATH}")
    df = spark.read.csv(SAMPLE_PATH, header=True, inferSchema=True)
    print(f"Rows loaded: {df.count()}")

    binary_model, scaler_model = load_binary_model(MODEL_PATH, SCALER_PATH)
    result = apply_binary_inference(df, binary_model, scaler_model)

    print("\nSample predictions:")
    result.select("binary_prediction", "binary_probability").show(5)

    spark.stop()
    print("\n✅ binary_inference.py standalone test passed.")
