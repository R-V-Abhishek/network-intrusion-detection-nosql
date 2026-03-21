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
echo -n "[run] Waiting for Cassandra to be ready..."
retry=0
until docker exec nids_cassandra cqlsh -e "describe keyspaces" > /dev/null 2>&1; do
  printf "."
  sleep 5
  retry=$((retry+1))
  if [ $retry -ge 12 ]; then
      echo " TIMEOUT"
      echo "[error] Cassandra failed to start in time. Check docker logs nids_cassandra."
      exit 1
  fi
done
echo " OK"

echo -n "[run] Waiting for Kafka to be ready..."
retry=0
until docker exec nids_kafka kafka-topics --bootstrap-server localhost:9092 --list > /dev/null 2>&1; do
  printf "."
  sleep 5
  retry=$((retry+1))
  if [ $retry -ge 12 ]; then
      echo " TIMEOUT"
      echo "[error] Kafka failed to start in time. Check docker logs nids_kafka."
      exit 1
  fi
done
echo " OK"

echo -n "[run] Waiting for Redis to be ready..."
retry=0
until docker exec nids_redis redis-cli ping > /dev/null 2>&1; do
  printf "."
  sleep 2
  retry=$((retry+1))
  if [ $retry -ge 15 ]; then
      echo " TIMEOUT"
      echo "[error] Redis failed to start in time. Check docker logs nids_redis."
      exit 1
  fi
done
echo " OK"

echo ""
echo "════════════════════════════════════════════"
echo "  All services ready!"
echo ""
echo "  Dashboard:       http://localhost:5000"
echo "  Kafka (external): localhost:19092"
echo "  Cassandra:       localhost:9042"
echo "  Redis:           localhost:6379"
echo "════════════════════════════════════════════"
