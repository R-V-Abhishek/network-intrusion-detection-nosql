# Network Intrusion Detection

A real-time network intrusion detection system built with Python, Redis, Cassandra, and Docker.

## Stack

- **Python** — Detection service & data pipeline
- **Redis** — Real-time event streaming and caching
- **Apache Cassandra** — Persistent storage for network events and alerts
- **Docker / Docker Compose** — Containerised deployment

## Getting Started

### Prerequisites

- Docker & Docker Compose

### Run

```bash
docker-compose up --build
```

## Project Structure

```
network-intrusion-detection/
├── src/                  # Application source code
├── docker-compose.yml    # Service orchestration
├── Dockerfile            # App container definition
├── requirements.txt      # Python dependencies
└── README.md
```
