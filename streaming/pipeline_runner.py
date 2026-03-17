"""
Pipeline runner for streaming inference.

Main entrypoint that orchestrates:
- Kafka stream consumption
- Binary and multiclass inference
- Alert storage in Cassandra + Redis
- Session management

Run with: python -m streaming.pipeline_runner
Test mode: STUB_MODELS=true python -m streaming.pipeline_runner
"""

import os
import sys
from typing import Optional
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import col, from_json, struct, to_json
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, DoubleType

from config.config import (
    KAFKA_CONFIG, SPARK_CONFIG, UNSW_FEATURE_CONFIG,
    UNSW_ATTACK_TYPE_MAPPING, ALERT_CONFIG, MODEL_PATHS
)
from alert_storage import AlertStorage, start_new_session, get_current_session_id

# Check if we're in stub mode (no real models)
STUB_MODELS = os.getenv("STUB_MODELS", "false").lower() == "true"

if not STUB_MODELS:
    # Import real inference modules when not in stub mode
    from streaming.binary_inference import load_binary_model, apply_binary_inference
    from streaming.multiclass_inference import load_multiclass_model, apply_multiclass_inference


def create_spark_session() -> SparkSession:
    """
    Create and configure Spark session for streaming.
    
    Returns:
        Configured SparkSession
    """
    spark = (
        SparkSession.builder
        .appName(SPARK_CONFIG["app_name"])
        .master(SPARK_CONFIG["master"])
        .config("spark.executor.memory", SPARK_CONFIG["executor_memory"])
        .config("spark.driver.memory", SPARK_CONFIG["driver_memory"])
        .config("spark.jars.packages", "org.apache.spark:spark-sql-kafka-0-10_2.12:3.5.0")
        .config("spark.sql.streaming.checkpointLocation", "/tmp/spark_checkpoints")
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
    df = (
        spark.readStream
        .format("kafka")
        .option("kafka.bootstrap.servers", KAFKA_CONFIG["bootstrap_servers"])
        .option("subscribe", topic)
        .option("startingOffsets", "latest")
        .load()
    )
    
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
    
    # Initialize storage
    storage = AlertStorage()
    if not storage.connect():
        print("[Pipeline] ERROR: Failed to connect to storage backends")
        return
    
    # Get or create session
    if session_id is None:
        session_id = get_current_session_id()
        if session_id is None:
            session_id = start_new_session(dataset=data_source)
    
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
    def process_batch(batch_df: DataFrame, batch_id: int):
        """
        Process each micro-batch from Kafka stream.
        
        Args:
            batch_df: DataFrame for current batch
            batch_id: Batch identifier
        """
        if batch_df.isEmpty():
            return
        
        print(f"\n[Batch {batch_id}] Processing {batch_df.count()} records...")
        
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
                batch_df = apply_multiclass_inference(batch_df, multiclass_model, label_mapping)
            
            # Filter to attack rows only (binary_prediction == 1)
            alerts_df = batch_df.filter(col("binary_prediction") == 1)
            
            alert_count = alerts_df.count()
            if alert_count > 0:
                print(f"[Batch {batch_id}] Found {alert_count} alerts, storing...")
                
                # Convert to list of dictionaries
                alerts = alerts_df.collect()
                
                for row in alerts:
                    # Build alert dictionary
                    alert = {
                        "binary_prediction": int(row.binary_prediction),
                        "binary_probability": float(row.binary_probability),
                        "attack_type": row.attack_type if hasattr(row, "attack_type") else "Unknown",
                        "attack_confidence": float(row.attack_confidence) if hasattr(row, "attack_confidence") else 0.0,
                        "severity": ALERT_CONFIG["severity_map"].get(
                            row.attack_type if hasattr(row, "attack_type") else "Unknown",
                            "medium"
                        ),
                        "src_ip": row.src_ip if hasattr(row, "src_ip") else "",
                        "dst_ip": row.dst_ip if hasattr(row, "dst_ip") else "",
                        "src_port": int(row.src_port) if hasattr(row, "src_port") else 0,
                        "dst_port": int(row.dst_port) if hasattr(row, "dst_port") else 0,
                        "protocol": row.proto if hasattr(row, "proto") else "",
                        "sbytes": int(row.sbytes) if hasattr(row, "sbytes") else 0,
                        "dbytes": int(row.dbytes) if hasattr(row, "dbytes") else 0,
                        "rate": float(row.rate) if hasattr(row, "rate") else 0.0,
                    }
                    
                    # Store alert
                    storage.store_alert(alert, session_id)
                
                print(f"[Batch {batch_id}] ✓ Stored {alert_count} alerts")
            else:
                print(f"[Batch {batch_id}] No alerts detected (all normal traffic)")
        
        except Exception as e:
            print(f"[Batch {batch_id}] ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    # Start streaming query
    print("\n[Pipeline] Starting streaming query...")
    print("[Pipeline] Press Ctrl+C to stop\n")
    
    query = (
        stream_df.writeStream
        .foreachBatch(process_batch)
        .outputMode("append")
        .trigger(processingTime="10 seconds")
        .start()
    )
    
    try:
        query.awaitTermination()
    except KeyboardInterrupt:
        print("\n[Pipeline] Stopping pipeline...")
        query.stop()
        storage.close()
        spark.stop()
        print("[Pipeline] Pipeline stopped gracefully")


if __name__ == "__main__":
    """
    Main entry point for pipeline runner.
    
    Usage:
        python -m streaming.pipeline_runner
        STUB_MODELS=true python -m streaming.pipeline_runner
    """
    run_pipeline()
