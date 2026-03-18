"""
Pipeline runner for streaming inference.

Main entrypoint that orchestrates:
- Kafka stream consumption
- Binary and multiclass inference
- Alert storage in Cassandra + ReCheckpoint INT-1 (Day 5 morning) — P1 + P3 syncdis
- Session management

Run with: python -m streaming.pipeline_runner
Test mode: STUB_MODELS=true python -m streaming.pipeline_runner
"""

import os
import sys
import pickle
import json
from typing import Optional
from datetime import datetime
import time
import numpy as np
import pyspark

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import col, from_json, struct, to_json
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, DoubleType

from config.config import (
    KAFKA_CONFIG, SPARK_CONFIG, STREAMING_CONFIG, UNSW_FEATURE_CONFIG,
    UNSW_ATTACK_TYPE_MAPPING, ALERT_CONFIG, MODEL_PATHS
)
from dashboard.storage import AlertStorage, start_new_session, get_current_session_id

# Check if we're in stub mode (no real models)
STUB_MODELS = os.getenv("STUB_MODELS", "false").lower() == "true"

# sklearn models (loaded at startup)
_binary_model = None
_multiclass_model = None
_scaler = None
_label_mapping = None
_reverse_mapping = None
_FEATURE_NAMES = UNSW_FEATURE_CONFIG["numeric_features"]


def _configure_windows_hadoop() -> None:
    """Configure Hadoop/winutils environment for Spark on Windows."""
    if os.name != "nt":
        return

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    hadoop_home = os.path.join(project_root, "tools", "hadoop")
    hadoop_bin = os.path.join(hadoop_home, "bin")
    winutils_path = os.path.join(hadoop_bin, "winutils.exe")

    if os.path.exists(winutils_path):
        os.environ["HADOOP_HOME"] = hadoop_home
        os.environ["hadoop.home.dir"] = hadoop_home
        path_value = os.environ.get("PATH", "")
        if hadoop_bin not in path_value.split(os.pathsep):
            os.environ["PATH"] = hadoop_bin + os.pathsep + path_value
        print(f"[Pipeline] HADOOP_HOME configured: {hadoop_home}")

    # Auto-detect JDK 17 (Java 24 is incompatible with PySpark)
    jdk17 = os.path.join(project_root, "tools", "jdk-17.0.12")
    if os.path.isdir(jdk17):
        os.environ["JAVA_HOME"] = jdk17
        print(f"[Pipeline] Using JDK 17: {jdk17}")


def _configure_java_compat() -> None:
    """Set JVM options needed by Hadoop/Spark on newer Java runtimes.

    Java 24+ completely removed Security Manager, so the
    -Djava.security.manager=allow flag would crash the JVM.
    We only add it for Java 17–23.
    """
    import subprocess

    flag = "-Djava.security.manager=allow"

    # Detect Java version
    java_major = 17  # default assumption
    try:
        java_bin = os.path.join(os.environ.get("JAVA_HOME", ""), "bin", "java")
        result = subprocess.run([java_bin, "-version"], capture_output=True, text=True, timeout=5)
        version_line = result.stderr.split("\n")[0] if result.stderr else ""
        import re
        m = re.search(r'"(\d+)', version_line)
        if m:
            java_major = int(m.group(1))
    except Exception:
        pass

    for var in ("JDK_JAVA_OPTIONS", "JAVA_TOOL_OPTIONS"):
        cur = os.environ.get(var, "")
        if java_major >= 24:
            # Strip the flag — Java 24 removed Security Manager
            cleaned = cur.replace(flag, "").strip()
            if cleaned:
                os.environ[var] = cleaned
            else:
                os.environ.pop(var, None)
        else:
            # Add the flag for Java 17–23
            if flag not in cur:
                os.environ[var] = (cur + " " + flag).strip()


def create_spark_session() -> SparkSession:
    """
    Create and configure Spark session for streaming.
    
    Returns:
        Configured SparkSession
    """
    _configure_windows_hadoop()
    _configure_java_compat()

    # Some Windows hostnames are not valid for Spark RPC URLs.
    os.environ.setdefault("SPARK_LOCAL_HOSTNAME", "localhost")
    os.environ.setdefault("SPARK_LOCAL_IP", "127.0.0.1")

    spark_version = pyspark.__version__
    spark_major = int(spark_version.split(".")[0])
    scala_suffix = "2.13" if spark_major >= 4 else "2.12"
    kafka_pkg = f"org.apache.spark:spark-sql-kafka-0-10_{scala_suffix}:{spark_version}"

    spark = (
        SparkSession.builder
        .appName(SPARK_CONFIG["app_name"])
        .master(SPARK_CONFIG["master"])
        .config("spark.executor.memory", SPARK_CONFIG["executor_memory"])
        .config("spark.driver.memory", SPARK_CONFIG["driver_memory"])
        .config("spark.driver.host", "127.0.0.1")
        .config("spark.driver.bindAddress", "127.0.0.1")
        .config("spark.jars.packages", kafka_pkg)
        .config("spark.sql.streaming.checkpointLocation", "/tmp/spark_checkpoints")
        .config("spark.sql.adaptive.enabled", "false")
        .getOrCreate()
    )
    
    spark.sparkContext.setLogLevel(SPARK_CONFIG["log_level"])
    print(f"[Pipeline] Spark session created: {SPARK_CONFIG['app_name']}")
    
    return spark


def build_kafka_stream(spark: SparkSession, topic: str) -> DataFrame:
    """
    Build Kafka streaming DataFrame.
    
    Args:
        spark: SparkSession
        topic: Kafka topic to consume from
        
    Returns:
        Streaming DataFrame
    """
    # Define schema matching UNSW_NB15_training-set.csv columns (after dropping 'id')
    schema = StructType(
        [StructField("dur", DoubleType(), True),
         StructField("proto", StringType(), True),
         StructField("service", StringType(), True),
         StructField("state", StringType(), True)]
        + [StructField(f, DoubleType(), True) for f in UNSW_FEATURE_CONFIG["numeric_features"]
           if f != "dur"]  # dur already listed above
        + [StructField("attack_cat", StringType(), True),
           StructField("label", IntegerType(), True)]
    )
    
    # Read from Kafka
    reader = (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_CONFIG["bootstrap_servers"])
        .option("subscribe", topic)
        .option("startingOffsets", "latest")
    )

    max_offsets = int(STREAMING_CONFIG.get("max_offsets_per_trigger", 0) or 0)
    if max_offsets > 0:
        reader = reader.option("maxOffsetsPerTrigger", str(max_offsets))

    df = reader.load()
    
    # Parse JSON value
    df = df.selectExpr("CAST(value AS STRING) as json_str")
    df = df.select(from_json(col("json_str"), schema).alias("data")).select("data.*")
    
    print(f"[Pipeline] Kafka stream connected to topic: {topic}")
    return df


def run_pipeline(data_source: str = "unsw", session_id: Optional[str] = None):
    """
    Run the full streaming pipeline.
    
    Args:
        data_source: Data source name (default: "unsw")
        session_id: Optional session ID (creates new if None)
    """
    global STUB_MODELS, _binary_model, _multiclass_model, _scaler, _label_mapping, _reverse_mapping

    print("=" * 80)
    print(f"[Pipeline] Starting NIDS Streaming Pipeline")
    print(f"[Pipeline] Data source: {data_source}")
    print(f"[Pipeline] Stub models: {STUB_MODELS}")
    print("=" * 80)
    
    # Initialize Spark
    spark = create_spark_session()

    # Initialize storage (falls back to in-memory if Redis is unavailable)
    storage = AlertStorage()
    storage.connect()

    # Get or create session
    if session_id is None:
        session_id = get_current_session_id()
        if session_id is None:
            session_id = start_new_session()
    
    print(f"[Pipeline] Session ID: {session_id}")
    
    # Load models if not in stub mode

    if not STUB_MODELS:
        print("[Pipeline] Loading sklearn models...")
        try:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            models_dir = os.path.join(project_root, "models")

            with open(os.path.join(models_dir, "binary_model.pkl"), "rb") as f:
                _binary_model = pickle.load(f)
            print(f"[Pipeline] Binary model: {type(_binary_model).__name__}")

            with open(os.path.join(models_dir, "multiclass_model.pkl"), "rb") as f:
                _multiclass_model = pickle.load(f)
            print(f"[Pipeline] Multiclass model: {type(_multiclass_model).__name__}")

            with open(os.path.join(models_dir, "scaler.pkl"), "rb") as f:
                _scaler = pickle.load(f)
            print(f"[Pipeline] Scaler loaded")

            with open(os.path.join(models_dir, "unsw_label_mapping.json"), "r") as f:
                mapping = json.load(f)
            _label_mapping = mapping.get("attack_mapping", {})
            _reverse_mapping = mapping.get("reverse_mapping", {})
            print(f"[Pipeline] Label mapping: {_label_mapping}")

            print("[Pipeline] All models loaded successfully")
        except Exception as e:
            print(f"[Pipeline] ERROR loading models: {e}")
            print("[Pipeline] Falling back to STUB mode")
            STUB_MODELS = True

    # Build streaming DataFrame
    stream_df = build_kafka_stream(spark, KAFKA_CONFIG["topic"])

    # Batch processing function
    def safe_int(value, default=0):
        try:
            if value is None:
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    def safe_float(value, default=0.0):
        try:
            if value is None:
                return default
            return float(value)
        except (TypeError, ValueError):
            return default

    def process_batch(batch_df: DataFrame, batch_id: int):
        """Process each micro-batch from Kafka stream using sklearn models."""
        if batch_df.isEmpty():
            return

        print(f"\n[Batch {batch_id}] Processing batch...")

        try:
            # Collect the Spark batch to pandas
            pdf = batch_df.toPandas()
            print(f"[Batch {batch_id}] Collected {len(pdf)} rows")

            if STUB_MODELS:
                # STUB MODE: Random predictions
                print(f"[Batch {batch_id}] Using STUB models")
                import random
                alert_payloads = []
                for _, row in pdf.iterrows():
                    if random.random() > 0.7:
                        alert_payloads.append({
                            "binary_prediction": 1,
                            "binary_probability": random.random(),
                            "attack_type": "Stub_Attack",
                            "attack_confidence": random.random(),
                            "severity": "medium",
                            "src_ip": "",
                            "dst_ip": "",
                            "src_port": 0,
                            "dst_port": 0,
                            "protocol": str(row.get("proto", "")),
                            "sbytes": safe_int(row.get("sbytes", 0)),
                            "dbytes": safe_int(row.get("dbytes", 0)),
                            "rate": safe_float(row.get("rate", 0.0)),
                        })
            else:
                # REAL MODE: sklearn inference
                # Prepare features — fill NaN/inf with 0
                X = pdf[_FEATURE_NAMES].copy() if all(c in pdf.columns for c in _FEATURE_NAMES) else pdf.reindex(columns=_FEATURE_NAMES, fill_value=0.0)
                X = X.fillna(0).replace([np.inf, -np.inf], 0).astype(float)
                X_scaled = _scaler.transform(X)

                # Binary classification
                binary_pred = _binary_model.predict(X_scaled)
                binary_proba = _binary_model.predict_proba(X_scaled)[:, 1]
                print(f"[Batch {batch_id}] Binary: {int(binary_pred.sum())} attacks / {len(binary_pred)} total")

                # Multiclass — only on predicted attacks
                attack_indices = np.where(binary_pred == 1)[0]
                mc_pred = np.full(len(pdf), -1, dtype=int)
                mc_proba = np.zeros(len(pdf))
                if len(attack_indices) > 0:
                    X_attacks = X_scaled[attack_indices]
                    mc_pred[attack_indices] = _multiclass_model.predict(X_attacks)
                    mc_proba_all = _multiclass_model.predict_proba(X_attacks)
                    mc_proba[attack_indices] = mc_proba_all.max(axis=1)

                # Build alert payloads (attacks only)
                alert_payloads = []
                for idx in attack_indices:
                    pred_id = int(mc_pred[idx])
                    attack_type = _reverse_mapping.get(str(pred_id), "Unknown")
                    row = pdf.iloc[idx]
                    alert_payloads.append({
                        "binary_prediction": 1,
                        "binary_probability": float(binary_proba[idx]),
                        "attack_type": attack_type,
                        "attack_confidence": float(mc_proba[idx]),
                        "severity": ALERT_CONFIG["severity_map"].get(attack_type, "medium"),
                        "src_ip": "",
                        "dst_ip": "",
                        "src_port": 0,
                        "dst_port": 0,
                        "protocol": str(row.get("proto", "")),
                        "sbytes": safe_int(row.get("sbytes", 0)),
                        "dbytes": safe_int(row.get("dbytes", 0)),
                        "rate": safe_float(row.get("rate", 0.0)),
                    })

            alert_count = len(alert_payloads)

            if alert_count > 0:
                store_start = time.monotonic()
                storage.store_alerts(alert_payloads, session_id)
                store_elapsed = time.monotonic() - store_start
                print(f"[Batch {batch_id}] Stored {alert_count} alerts in {store_elapsed:.2f}s")
            else:
                print(f"[Batch {batch_id}] No alerts (all normal traffic)")
        
        except Exception as e:
            print(f"[Batch {batch_id}] ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    # Start streaming query
    print("\n[Pipeline] Starting streaming query...")
    print("[Pipeline] Press Ctrl+C to stop\n")
    
    trigger_interval = STREAMING_CONFIG.get("trigger_interval", "30 seconds")
    print(f"[Pipeline] Trigger interval: {trigger_interval}")

    query = (
        stream_df.writeStream
        .foreachBatch(process_batch)
        .outputMode("append")
        .trigger(processingTime=trigger_interval)
        .start()
    )
    
    try:
        query.awaitTermination()
    except KeyboardInterrupt:
        print("\n[Pipeline] Stopping pipeline...")
    except Exception as exc:
        print(f"\n[Pipeline] Streaming loop ended with exception: {exc}")
    finally:
        try:
            if query.isActive:
                query.stop()
        except Exception:
            pass
        storage.close()
        try:
            spark.stop()
        except Exception:
            pass
        print("[Pipeline] Pipeline stopped gracefully")


if __name__ == "__main__":
    """
    Main entry point for pipeline runner.
    
    Usage:
        python -m streaming.pipeline_runner
        STUB_MODELS=true python -m streaming.pipeline_runner
    """
    run_pipeline()
