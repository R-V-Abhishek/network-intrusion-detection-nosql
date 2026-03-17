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
from typing import Optional
from datetime import datetime
import time
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

if not STUB_MODELS:
    # Import real inference modules when not in stub mode
    from streaming.binary_inference import load_binary_model, apply_binary_inference
    from streaming.multiclass_inference import load_multiclass_model, apply_multiclass_inference


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


def _configure_java_compat() -> None:
    """Set JVM options needed by Hadoop/Spark on newer Java runtimes."""
    required_opt = "-Djava.security.manager=allow"

    current_jdk_opts = os.environ.get("JDK_JAVA_OPTIONS", "")
    if required_opt not in current_jdk_opts:
        os.environ["JDK_JAVA_OPTIONS"] = (current_jdk_opts + " " + required_opt).strip()

    current_tool_opts = os.environ.get("JAVA_TOOL_OPTIONS", "")
    if required_opt not in current_tool_opts:
        os.environ["JAVA_TOOL_OPTIONS"] = (current_tool_opts + " " + required_opt).strip()


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
    # Define schema for UNSW-NB15 network traffic
    schema = StructType([
        StructField(feature, DoubleType(), True)
        for feature in UNSW_FEATURE_CONFIG["numeric_features"]
    ] + [
        StructField("label", IntegerType(), True),
        StructField("attack_cat", StringType(), True),
        StructField("src_ip", StringType(), True),
        StructField("dst_ip", StringType(), True),
        StructField("src_port", IntegerType(), True),
        StructField("dst_port", IntegerType(), True),
        StructField("proto", StringType(), True),
    ])
    
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
    global STUB_MODELS

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
        print("[Pipeline] Loading models...")
        try:
            binary_model, scaler = load_binary_model(MODEL_PATHS["unsw_gbt_binary"], MODEL_PATHS["unsw_nb15_scaler"])
            multiclass_model = load_multiclass_model(
                MODEL_PATHS["unsw_multiclass"]
            )
            
            # Load label mapping
            import json
            with open(MODEL_PATHS["label_mapping"], "r") as f:
                label_mapping = json.load(f)
            
            print("[Pipeline] Models loaded successfully")
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
        """
        Process each micro-batch from Kafka stream.
        
        Args:
            batch_df: DataFrame for current batch
            batch_id: Batch identifier
        """
        if batch_df.isEmpty():
            return

        print(f"\n[Batch {batch_id}] Processing batch...")
        
        try:
            if STUB_MODELS:
                # STUB MODE: Generate fake predictions for testing
                print(f"[Batch {batch_id}] Using STUB models")
                
                # Add stub prediction columns
                from pyspark.sql.functions import lit, rand
                batch_df = batch_df.withColumn("binary_prediction", 
                                               (rand() > 0.7).cast("int"))
                batch_df = batch_df.withColumn("binary_probability", rand())
                batch_df = batch_df.withColumn("attack_type", lit("Stub_Attack"))
                batch_df = batch_df.withColumn("attack_confidence", rand())
                
            else:
                # REAL MODE: Use trained models
                print(f"[Batch {batch_id}] Applying binary inference...")
                batch_df = apply_binary_inference(batch_df, binary_model, scaler)

                print(f"[Batch {batch_id}] Applying multiclass inference...")
                batch_df = apply_multiclass_inference(
                    batch_df,
                    multiclass_model,
                    label_mapping,
                    include_normal_rows=False,
                )

            # In real mode, multiclass output is already attack-only.
            alerts_df = batch_df.filter(col("binary_prediction") == 1) if STUB_MODELS else batch_df

            # Use a single Spark action (collect once) to avoid count+collect double jobs.
            alert_fields = [
                "binary_prediction",
                "binary_probability",
                "attack_type",
                "attack_confidence",
                "src_ip",
                "dst_ip",
                "src_port",
                "dst_port",
                "proto",
                "sbytes",
                "dbytes",
                "rate",
            ]
            selected_fields = [c for c in alert_fields if c in alerts_df.columns]
            collect_start = time.monotonic()
            alerts = alerts_df.select(*selected_fields).collect()
            collect_elapsed = time.monotonic() - collect_start
            alert_count = len(alerts)

            if alert_count > 0:
                print(
                    f"[Batch {batch_id}] Found {alert_count} alerts, "
                    f"materialized in {collect_elapsed:.2f}s, storing..."
                )

                store_start = time.monotonic()
                
                alert_payloads = []
                for row in alerts:
                    # Build alert dictionary
                    alert = {
                        "binary_prediction": safe_int(getattr(row, "binary_prediction", 0)),
                        "binary_probability": safe_float(getattr(row, "binary_probability", 0.0)),
                        "attack_type": row.attack_type if hasattr(row, "attack_type") else "Unknown",
                        "attack_confidence": safe_float(getattr(row, "attack_confidence", 0.0)),
                        "severity": ALERT_CONFIG["severity_map"].get(
                            row.attack_type if hasattr(row, "attack_type") else "Unknown",
                            "medium"
                        ),
                        "src_ip": row.src_ip if hasattr(row, "src_ip") else "",
                        "dst_ip": row.dst_ip if hasattr(row, "dst_ip") else "",
                        "src_port": safe_int(getattr(row, "src_port", 0)),
                        "dst_port": safe_int(getattr(row, "dst_port", 0)),
                        "protocol": row.proto if hasattr(row, "proto") else "",
                        "sbytes": safe_int(getattr(row, "sbytes", 0)),
                        "dbytes": safe_int(getattr(row, "dbytes", 0)),
                        "rate": safe_float(getattr(row, "rate", 0.0)),
                    }

                    alert_payloads.append(alert)

                storage.store_alerts(alert_payloads, session_id)

                store_elapsed = time.monotonic() - store_start
                print(f"[Batch {batch_id}] OK Stored {alert_count} alerts in {store_elapsed:.2f}s")
            else:
                print(f"[Batch {batch_id}] No alerts detected (all normal traffic)")
        
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
