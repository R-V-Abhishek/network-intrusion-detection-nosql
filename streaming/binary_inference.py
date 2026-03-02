"""
Binary inference module for UNSW-NB15 streaming pipeline.

Loads the trained GBT binary classifier and StandardScaler, assembles features,
and applies binary (normal/attack) prediction to incoming Spark DataFrames.
"""

from typing import Tuple

from pyspark.ml.classification import GBTClassificationModel
from pyspark.ml.feature import StandardScalerModel, VectorAssembler
from pyspark.sql import DataFrame
from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType


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
    # Cast all feature columns to DoubleType and fill nulls/infinities
    for col in feature_cols:
        if col in df.columns:
            df = df.withColumn(
                col,
                F.when(F.col(col).isNull(), 0.0)
                .when(F.col(col) == float("inf"), 0.0)
                .when(F.col(col) == float("-inf"), 0.0)
                .otherwise(F.col(col).cast(DoubleType())),
            )

    available = [c for c in feature_cols if c in df.columns]
    assembler = VectorAssembler(
        inputCols=available,
        outputCol="features_raw",
        handleInvalid="skip",
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
        # Derive feature list from the scaler's input metadata where possible;
        # fall back to all numeric columns except known label/id cols.
        exclude = {"label", "binary_label", "multiclass_label", "attack_cat", "id"}
        numeric_cols = [
            f.name
            for f in df.schema.fields
            if str(f.dataType) in ("DoubleType()", "FloatType()", "IntegerType()", "LongType()")
            and f.name not in exclude
        ]
        df = assemble_features(df, numeric_cols)

    # Scale features
    df = scaler.transform(df).withColumnRenamed("features_scaled", "features_vec")

    # Run GBT inference (expects features column named 'features_scaled')
    # Temporarily alias so the model's featuresCol matches
    df = df.withColumnRenamed("features_vec", "features_scaled")
    df = model.transform(df)
    df = df.withColumnRenamed("features_scaled", "features_vec")

    # Rename model output columns to pipeline-standard names
    df = df.withColumnRenamed("prediction", "binary_prediction")

    # Extract probability of the positive (Attack) class from the probability vector
    extract_prob = F.udf(lambda v: float(v[1]) if v is not None else 0.0, DoubleType())
    df = df.withColumn("binary_probability", extract_prob(F.col("probability")))
    df = df.drop("probability", "rawPrediction")

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
    SCALER_PATH = str(MODEL_DIR / "unsw_scaler")

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
