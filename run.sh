#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# run.sh — Start the full NIDS stack and wait for services to be ready
# ──────────────────────────────────────────────────────────────────────
set -e

echo "╔══════════════════════════════════════════╗"
echo "║   NIDS — Network Intrusion Detection     ║"
echo "╚══════════════════════════════════════════╝"
echo ""

echo "[run] Starting Docker Compose stack..."
docker compose up --build -d

echo ""
echo "[run] Waiting for Cassandra to be ready..."
until docker exec nids_cassandra cqlsh -e "describe keyspaces" > /dev/null 2>&1; do
  printf "."
  sleep 5
done
echo " OK"

echo "[run] Waiting for Kafka to be ready..."
until docker exec nids_kafka kafka-topics --bootstrap-server localhost:9092 --list > /dev/null 2>&1; do
  printf "."
  sleep 5
done
echo " OK"

echo "[run] Waiting for Redis to be ready..."
until docker exec nids_redis redis-cli ping > /dev/null 2>&1; do
  printf "."
  sleep 2
done
echo " OK"

echo ""
echo "════════════════════════════════════════════"
echo "  All services ready!"
echo ""
echo "  Dashboard:       http://localhost:5000"
echo "  Kafka (external): localhost:19092"
echo "  Cassandra:       localhost:19042"
echo "  Redis:           localhost:6379"
echo "════════════════════════════════════════════"
