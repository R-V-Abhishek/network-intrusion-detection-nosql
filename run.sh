#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════
# NIDS Startup Script
# 
# Starts all Docker services with proper healthchecks and displays
# service URLs when everything is ready.
# ══════════════════════════════════════════════════════════════════════════

set -e

echo "══════════════════════════════════════════════════════════════════════════"
echo "  NIDS - Network Intrusion Detection System"
echo "  Starting all services..."
echo "══════════════════════════════════════════════════════════════════════════"
echo ""

# Start all services
echo "[1/4] Starting Docker Compose services..."
docker compose up --build -d

echo ""
echo "[2/4] Waiting for Cassandra to be ready..."
until docker exec nids-cassandra cqlsh -e "describe keyspaces" > /dev/null 2>&1; do
    echo "  ⏳ Cassandra not ready yet, retrying in 5 seconds..."
    sleep 5
done
echo "  ✓ Cassandra is ready"

echo ""
echo "[3/4] Waiting for Kafka to be ready..."
until docker exec nids-kafka kafka-topics --bootstrap-server localhost:9092 --list > /dev/null 2>&1; do
    echo "  ⏳ Kafka not ready yet, retrying in 5 seconds..."
    sleep 5
done
echo "  ✓ Kafka is ready"

echo ""
echo "[4/4] Waiting for Redis to be ready..."
until docker exec nids-redis redis-cli ping > /dev/null 2>&1; do
    echo "  ⏳ Redis not ready yet, retrying in 5 seconds..."
    sleep 3
done
echo "  ✓ Redis is ready"

echo ""
echo "══════════════════════════════════════════════════════════════════════════"
echo "  All services are ready!"
echo "══════════════════════════════════════════════════════════════════════════"
echo ""
echo "Service URLs:"
echo "  ┌─────────────────────────────────────────────────────────────────"
echo "  │ Dashboard:       http://localhost:5000"
echo "  │ Kafka UI:        http://localhost:8080"
echo "  │ Cassandra Web:   http://localhost:8081"
echo "  │ Redis Insight:   http://localhost:5540"
echo "  └─────────────────────────────────────────────────────────────────"
echo ""
echo "Next steps:"
echo "  1. Start the Flask dashboard:     python dashboard/app.py"
echo "  2. Start the streaming pipeline:  python -m streaming.pipeline_runner"
echo "  3. Start the data producer:       python kafka_producer.py --data-source unsw"
echo ""
echo "To view logs:"
echo "  docker compose logs -f [service-name]"
echo ""
echo "To stop all services:"
echo "  docker compose down"
echo ""
echo "══════════════════════════════════════════════════════════════════════════"
