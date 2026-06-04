.PHONY: help install lint test test-all \
        infra infra-stop dashboard pipeline pipeline-stub producer sync-push build clean

# ── Single venv — used for everything ────────────────────────────────────────
VENV     := venv\Scripts
JAVA17   := $(CURDIR)\tools\jdk-17.0.12

IMAGE_NAME := nids-app
IMAGE_TAG  := latest

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  --- Setup ---"
	@echo "  install       Create venv and install all dependencies"
	@echo ""
	@echo "  --- Quality ---"
	@echo "  lint          Run flake8 linter"
	@echo "  test          Run unit tests (no Docker needed)"
	@echo "  test-all      Run unit + integration tests (needs Redis on :6379)"
	@echo ""
	@echo "  --- Local Stack ---"
	@echo "  infra         Start Redis + Kafka + Cassandra (Docker)"
	@echo "  infra-stop    Stop all Docker infra containers"
	@echo "  dashboard     Start Flask dashboard at http://localhost:5000"
	@echo "  pipeline      Start Spark streaming pipeline (real models)"
	@echo "  pipeline-stub Start Spark pipeline with STUB_MODELS=true"
	@echo "  producer      Stream sample.csv to Kafka (10 rows/sec, loops)"
	@echo "  sync-push     Push local Redis alerts to EC2 once"
	@echo ""
	@echo "  --- Docker ---"
	@echo "  build         Build EC2-optimized Docker image"
	@echo "  clean         Remove venv, caches, build artifacts"

# ── Setup ─────────────────────────────────────────────────────────────────────

install:
	python -m venv venv
	$(VENV)\python.exe -m pip install --upgrade pip
	$(VENV)\python.exe -m pip install -r requirements.txt

# ── Code Quality ──────────────────────────────────────────────────────────────

lint:
	$(VENV)\flake8.exe config/ src/ streaming/ dashboard/ tests/ sync_push.py \
		--max-line-length=110 \
		--exclude=venv \
		--count

test:
	set NIDS_DISABLE_CASSANDRA=1 && \
	set PYTHONPATH=.;src && \
	$(VENV)\pytest.exe tests/ -v --tb=short --ignore=tests/test_integration_storage_smoke.py

test-all:
	docker compose -f docker-compose.ci.yml up -d --wait
	set NIDS_RUN_INTEGRATION=1 && \
	set PYTHONPATH=.;src && \
	$(VENV)\pytest.exe tests/ -v --tb=short
	docker compose -f docker-compose.ci.yml down --remove-orphans

# ── Local Dev Infrastructure ──────────────────────────────────────────────────

infra:
	docker compose -f docker-compose.local.yml --profile full up -d
	@echo "[OK] Redis :6379 | Kafka :19092 | Cassandra :19042"

infra-stop:
	docker compose -f docker-compose.local.yml --profile full down --remove-orphans

# ── Local Dev Processes (run each in a separate terminal) ─────────────────────

dashboard:
	set PYTHONPATH=.;src && \
	set NIDS_DISABLE_CASSANDRA=1 && \
	set REDIS_HOST=localhost && \
	set REDIS_PORT=6379 && \
	$(VENV)\python.exe -m flask --app dashboard.app run --host 0.0.0.0 --port 5000 --debug

pipeline:
	set JAVA_HOME=$(JAVA17) && \
	set PYTHONPATH=.;src && \
	set NIDS_DISABLE_CASSANDRA=1 && \
	set REDIS_HOST=localhost && \
	set REDIS_PORT=6379 && \
	set KAFKA_BOOTSTRAP_SERVERS=localhost:19092 && \
	$(VENV)\python.exe -m streaming.pipeline_runner

pipeline-stub:
	set JAVA_HOME=$(JAVA17) && \
	set PYTHONPATH=.;src && \
	set NIDS_DISABLE_CASSANDRA=1 && \
	set REDIS_HOST=localhost && \
	set REDIS_PORT=6379 && \
	set STUB_MODELS=true && \
	set KAFKA_BOOTSTRAP_SERVERS=localhost:19092 && \
	$(VENV)\python.exe -m streaming.pipeline_runner

producer:
	set PYTHONPATH=.;src && \
	set KAFKA_BOOTSTRAP_SERVERS=localhost:19092 && \
	$(VENV)\python.exe kafka_producer.py \
		--file data/UNSW-NB15/sample.csv \
		--rate 10 \
		--loop

sync-push:
	set PYTHONPATH=.;src && \
	set LOCAL_REDIS_HOST=localhost && \
	set LOCAL_REDIS_PORT=6379 && \
	set SYNC_SESSION_ID=local-session && \
	$(VENV)\python.exe sync_push.py

# ── Docker ────────────────────────────────────────────────────────────────────

build:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) -f Dockerfile.ec2 .

# ── Clean ─────────────────────────────────────────────────────────────────────

clean:
	if exist venv rmdir /s /q venv
	if exist .venv rmdir /s /q .venv
	if exist .pytest_cache rmdir /s /q .pytest_cache
	if exist htmlcov rmdir /s /q htmlcov
	if exist .coverage del .coverage
	if exist coverage.xml del coverage.xml
	if exist test-results.xml del test-results.xml
	for /d /r . %%d in (__pycache__) do @if exist "%%d" rmdir /s /q "%%d"
