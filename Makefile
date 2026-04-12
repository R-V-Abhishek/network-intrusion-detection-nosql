.PHONY: help install lint test test-all build run stop clean

VENV        := venv/bin
IMAGE_NAME  := nids-app
IMAGE_TAG   := latest

help:
	@echo "Usage: make <target>"
	@echo ""
	@echo "  install     Create venv and install dependencies"
	@echo "  lint        Run flake8"
	@echo "  test        Run unit tests (no external services needed)"
	@echo "  test-all    Run unit + integration tests (requires docker-compose.ci.yml)"
	@echo "  build       Build Docker image"
	@echo "  run         Start full stack (docker compose up)"
	@echo "  stop        Stop full stack"
	@echo "  clean       Remove venv, cache, build artifacts"

install:
	python3 -m venv venv
	$(VENV)/pip install --upgrade pip
	$(VENV)/pip install -r requirements.txt

lint:
	$(VENV)/flake8 config/ src/ streaming/ dashboard/ tests/ \
		--max-line-length=110 \
		--exclude=venv \
		--count

test:
	$(VENV)/pytest tests/ -v --tb=short

test-all:
	docker compose -f docker-compose.ci.yml up -d --wait
	NIDS_RUN_INTEGRATION=1 $(VENV)/pytest tests/ -v --tb=short; \
	docker compose -f docker-compose.ci.yml down --remove-orphans

build:
	docker build -t $(IMAGE_NAME):$(IMAGE_TAG) .

run:
	docker compose -f docker-compose.yml up -d --build --wait
	@echo "Dashboard: http://localhost:5000"

stop:
	docker compose -f docker-compose.yml down

clean:
	rm -rf venv .pytest_cache __pycache__ .coverage htmlcov coverage.xml test-results.xml
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
