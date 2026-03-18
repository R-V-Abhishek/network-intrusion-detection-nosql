"""
Kafka producer for NIDS streaming pipeline.

Reads UNSW-NB15 CSV data and publishes rows as JSON messages to Kafka
at a configurable rate. Designed for both integration testing (sample.csv)
and full-throughput simulation.

Usage:
    # Integration test with sample.csv at 10 rows/sec:
    python kafka_producer.py --data-source unsw

    # Full dataset at 500 rows/sec:
    python kafka_producer.py --data-source unsw --rate 500

    # Specific CSV file:
    python kafka_producer.py --data-source unsw --file data/UNSW-NB15/sample.csv

    # Loop continuously through the file:
    python kafka_producer.py --data-source unsw --loop
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
from kafka import KafkaProducer
from kafka.errors import NoBrokersAvailable

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:19092")
DEFAULT_TOPIC = os.getenv("KAFKA_TOPIC", "network-traffic")
DEFAULT_SAMPLE = str(REPO_ROOT / "data" / "UNSW-NB15" / "Training and Testing Sets" / "UNSW_NB15_training-set.csv")
DEFAULT_RATE = 10  # rows per second

# Columns to drop before publishing (not needed by inference)
DROP_COLS = {"id"}


# ---------------------------------------------------------------------------
# Producer helpers
# ---------------------------------------------------------------------------

def build_producer(bootstrap_servers: str, retries: int = 5) -> KafkaProducer:
    """Connect to Kafka with retry logic."""
    for attempt in range(1, retries + 1):
        try:
            producer = KafkaProducer(
                bootstrap_servers=bootstrap_servers,
                value_serializer=lambda v: json.dumps(v).encode("utf-8"),
                acks="all",
                retries=3,
            )
            print(f"[Producer] Connected to Kafka at {bootstrap_servers}")
            return producer
        except NoBrokersAvailable:
            wait = attempt * 3
            print(f"[Producer] No brokers available (attempt {attempt}/{retries}), retrying in {wait}s...")
            time.sleep(wait)
    raise RuntimeError(f"Could not connect to Kafka at {bootstrap_servers} after {retries} attempts")


def load_csv(file_path: str) -> pd.DataFrame:
    """Load a CSV and clean it for publishing."""
    print(f"[Producer] Loading: {file_path}")
    df = pd.read_csv(file_path, low_memory=False)

    # Normalise column names
    df.columns = [c.strip().lower() for c in df.columns]

    # Drop columns not needed downstream
    drop = [c for c in DROP_COLS if c in df.columns]
    if drop:
        df = df.drop(columns=drop)

    # Replace NaN/inf with None so JSON serialiser doesn't choke
    df = df.where(pd.notnull(df), None)

    print(f"[Producer] Loaded {len(df)} rows, {len(df.columns)} columns")
    return df


def publish(
    producer: KafkaProducer,
    df: pd.DataFrame,
    topic: str,
    rate: float,
    loop: bool = False,
) -> None:
    """
    Publish rows from df to the Kafka topic at the given rate (rows/sec).

    Parameters
    ----------
    producer : KafkaProducer
    df : pd.DataFrame
        Rows to publish.
    topic : str
        Kafka topic name.
    rate : float
        Rows per second to publish. Use 0 for maximum throughput.
    loop : bool
        If True, cycle through df indefinitely until Ctrl+C.
    """
    delay = 1.0 / rate if rate > 0 else 0

    total_sent = 0
    iteration = 0

    try:
        while True:
            iteration += 1
            if loop or iteration == 1:
                if iteration > 1:
                    print(f"\n[Producer] Looping — iteration {iteration}")
            else:
                pass  # single pass, break at end

            for _, row in df.iterrows():
                record = row.to_dict()
                producer.send(topic, value=record)
                total_sent += 1

                if delay:
                    time.sleep(delay)

                if total_sent % 50 == 0:
                    print(f"[Producer] Sent {total_sent} messages...", end="\r")

            producer.flush()
            print(f"[Producer] OK Flushed batch -- total sent: {total_sent}")

            if not loop:
                break

    except KeyboardInterrupt:
        producer.flush()
        print(f"\n[Producer] Interrupted — total sent: {total_sent}")

    print(f"[Producer] Done. Total messages sent: {total_sent}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Kafka producer for NIDS UNSW-NB15 pipeline"
    )
    parser.add_argument(
        "--data-source",
        default="unsw",
        choices=["unsw"],
        help="Dataset to stream (default: unsw)",
    )
    parser.add_argument(
        "--file",
        default=None,
        help=(
            "Path to a specific CSV file to stream. "
            f"Defaults to data/UNSW-NB15/sample.csv"
        ),
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=DEFAULT_RATE,
        help=f"Rows per second to publish (default: {DEFAULT_RATE}). Use 0 for max throughput.",
    )
    parser.add_argument(
        "--topic",
        default=DEFAULT_TOPIC,
        help=f"Kafka topic to publish to (default: {DEFAULT_TOPIC})",
    )
    parser.add_argument(
        "--bootstrap-servers",
        default=DEFAULT_BOOTSTRAP,
        help=f"Kafka bootstrap servers (default: {DEFAULT_BOOTSTRAP})",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Loop through the file indefinitely (useful for sustained load testing)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Resolve file path
    csv_path = args.file if args.file else DEFAULT_SAMPLE
    if not Path(csv_path).exists():
        print(f"[Producer] ERROR: File not found: {csv_path}")
        sys.exit(1)

    print("=" * 60)
    print("[Producer] NIDS Kafka Producer")
    print(f"  Topic:    {args.topic}")
    print(f"  Brokers:  {args.bootstrap_servers}")
    print(f"  File:     {csv_path}")
    print(f"  Rate:     {args.rate} rows/sec" if args.rate > 0 else "  Rate:     max throughput")
    print(f"  Loop:     {args.loop}")
    print("=" * 60)

    df = load_csv(csv_path)
    producer = build_producer(args.bootstrap_servers)

    publish(producer, df, topic=args.topic, rate=args.rate, loop=args.loop)

    producer.close()


if __name__ == "__main__":
    main()
