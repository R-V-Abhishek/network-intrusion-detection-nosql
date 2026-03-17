# NIDS Project Memory

## Project Overview
Network Intrusion Detection System using UNSW-NB15 dataset.
Stack: Kafka → PySpark Structured Streaming → Redis/Cassandra → Flask dashboard.

## Key File Paths
- `config/config.py` — central config (Kafka, Spark, Redis, Cassandra, model paths)
- `kafka_producer.py` — publishes UNSW-NB15 CSV rows to Kafka
- `streaming/pipeline_runner.py` — main Spark streaming pipeline entrypoint
- `streaming/binary_inference.py` — GBT binary classifier (normal/attack)
- `streaming/multiclass_inference.py` — RF multiclass classifier (attack type)
- `dashboard/app.py` — Flask app factory
- `dashboard/storage.py` — AlertStorage: Redis-backed with in-memory fallback
- `dashboard/api_alerts.py` — /api/alerts blueprint
- `dashboard/api_analytics.py` — /api/alerts/stats, /timeline blueprints

## Architecture Notes
- Kafka topic: `network-traffic`, bootstrap: `localhost:19092` (host) or `nids_kafka:9092` (Docker)
- All infra hostnames read from env vars in config.py (REDIS_HOST, CASSANDRA_HOST, KAFKA_BOOTSTRAP_SERVERS)
- AlertStorage uses `nids:alerts:{session_id}` and `nids:sessions` Redis key patterns
- Default session_id is `"local-session"`; pipeline and dashboard use the same session by default
- Cassandra config exists but AlertStorage does NOT use Cassandra — Redis only

## Bugs Fixed (Session 1)
1. **binary_inference.py:130** — `F.udf` lambda caused Python worker crash (WinError 10038 on Windows).
   Fixed by replacing with `vector_to_array` + native Spark column ops (same pattern as multiclass_inference.py).
2. **config.py** — REDIS_CONFIG, CASSANDRA_CONFIG, KAFKA_CONFIG were hardcoded; now read from env vars.
3. **docker-compose.yml** — Cassandra had no host port mapping; added `ports: "9042:9042"`.
   Also: Kafka now has dual listeners (PLAINTEXT internal + EXTERNAL for host), app container has all env vars.
4. **pipeline_runner.py:177** — `if not storage.connect()` was dead (always True); removed dead guard.

## Common Pitfalls
- Never use F.udf in this Spark pipeline on Windows — use native Spark functions or vector_to_array
- storage.connect() always returns True by design (in-memory fallback is acceptable)
- pipeline_runner.py creates its own AlertStorage() instance (not the singleton from get_storage())
- The pipeline runs OUTSIDE Docker normally; docker-compose is for infra services only
