# Network Intrusion Detection System (NIDS)

A **real-time network intrusion detection system** built with Apache Spark Structured Streaming, Apache Kafka, Apache Cassandra, and Redis. The system performs **two-stage ML inference** — binary classification (normal vs attack) followed by multiclass classification (attack type identification) — on live network traffic and surfaces results through an interactive Flask dashboard.

> **Dataset:** [UNSW-NB15](https://research.unsw.edu.au/projects/unsw-nb15-dataset) — 39 numeric features, 10 attack categories, 2.5M+ records.

---

## Architecture

```
┌─────────────┐     ┌───────────┐     ┌──────────────────────────────────┐
│  CSV Data   │────▶│   Kafka   │────▶│   Spark Structured Streaming     │
│  (Producer) │     │  (Broker) │     │                                  │
└─────────────┘     └───────────┘     │  1. Binary Inference (GBT)       │
                                      │     Normal ──▶ skip              │
                                      │     Attack ──▶ step 2            │
                                      │  2. Multiclass Inference (RF)    │
                                      │     Predict attack category      │
                                      │  3. Store alerts                 │
                                      └───────────┬────────────┬─────────┘
                                                  │            │
                                           ┌──────▼──┐   ┌─────▼──────┐
                                           │  Redis  │   │ Cassandra  │
                                           │ (cache) │   │ (durable)  │
                                           └────┬────┘   └────────────┘
                                                │
                                         ┌──────▼──────┐
                                         │   Flask     │
                                         │  Dashboard  │
                                         │  :5000      │
                                         └─────────────┘
```

### Why Two Databases?

| | **Apache Cassandra** | **Redis** |
|---|---|---|
| **Role** | Durable, persistent storage | Fast in-memory cache & pub/sub |
| **Stores** | All alerts permanently (partitioned by session, clustered by time DESC) | Recent alerts list, session metadata, real-time pub/sub channel a|
| **Why we need it** | Survives restarts, handles millions of alerts, supports time-range queries | Dashboard needs sub-millisecond reads for live feed, avoids hammering Cassandra on every page refresh |
| **Query pattern** | `SELECT * FROM alerts WHERE session_id = ? ORDER BY alert_time DESC` | `LRANGE nids:alerts:<session> 0 99` |
| **Data model** | Wide-column (partition key: session_id, clustering: alert_time DESC) | Key-value lists + hashes |

**In short:** Cassandra = source of truth, Redis = speed layer for the dashboard.

---

## Tech Stack

| Component | Technology | Purpose |
|---|---|---|
| **Message Broker** | Apache Kafka (KRaft mode) | Stream network traffic records |
| **Stream Processing** | PySpark Structured Streaming | Consume Kafka, run ML inference |
| **Binary Classifier** | Spark ML GBTClassifier | Detect attack vs normal (AUC ~0.97) |
| **Multiclass Classifier** | Spark ML RandomForestClassifier | Identify attack type (10 categories) |
| **Persistent Storage** | Apache Cassandra 4.1 | Store alerts durably |
| **Cache / Pub-Sub** | Redis 7 | Fast dashboard reads, live feed |
| **Dashboard** | Flask + Chart.js | Real-time web UI |
| **CI/CD** | Jenkins + Docker | Automated lint, test, build pipeline |

---

## Project Structure

```
network-intrusion-detection-nosql/
├── config/
│   ├── config.py                  # Centralized config (Kafka, Spark, features, models, alert severity)
│   └── __init__.py
├── streaming/
│   ├── binary_inference.py        # GBT binary classifier (normal vs attack)
│   ├── multiclass_inference.py    # RF multiclass classifier (attack type)
│   └── pipeline_runner.py         # Main pipeline: Kafka → inference → storage
├── dashboard/
│   ├── app.py                     # Flask app with session + health APIs
│   ├── api_alerts.py              # GET /api/alerts endpoints
│   ├── api_analytics.py           # GET /api/alerts/stats, timeline, attack-types
│   ├── storage.py                 # Cassandra + Redis + in-memory fallback
│   └── templates/
│       ├── base.html              # Dark-themed layout with Chart.js
│       ├── dashboard.html         # Live dashboard with severity gauge
│       ├── alerts.html            # Filterable, sortable alerts table
│       ├── analytics.html         # Bar/line charts for attack analytics
│       └── settings.html          # Session management + service health
├── scripts/
│   ├── preprocess_unsw_nb15.py    # UNSW-NB15 data preprocessing
│   └── run_preprocessing.py       # CLI runner for preprocessing
├── src/
│   ├── preprocessing_utils.py     # Utilities: clip, encode, validate, split
│   └── main.py
├── tests/
│   ├── test_config.py             # Config validation tests
│   ├── test_dashboard_api.py      # API contract tests
│   └── test_pipeline.py           # Pipeline logic tests
├── data/UNSW-NB15/                # Raw dataset CSVs + sample.csv
├── models/                        # Trained ML models (after running notebook)
├── kafka_producer.py              # Kafka producer — streams CSV rows
├── unsw_model_training.ipynb      # Jupyter notebook — train both classifiers
├── unsw_feature_names.json        # Locked 39-feature schema
├── docker-compose.yml             # Cassandra + Redis + Kafka
├── Dockerfile                     # App container
├── Jenkinsfile                    # CI/CD pipeline
├── requirements.txt               # Python dependencies
└── run.sh                         # One-command startup script
```

---

## Getting Started

### Prerequisites

- **Python 3.10+** with `pip`
- **Java 11+** (required by PySpark)
- **Docker & Docker Compose** (for Cassandra, Redis, Kafka)

### 1. Clone & Setup Python Environment

```bash
git clone <repo-url>
cd network-intrusion-detection-nosql

# Create virtual environment
python -m venv venv

# Activate (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Activate (Linux/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Download the Dataset

Download the [UNSW-NB15 training set CSV](https://research.unsw.edu.au/projects/unsw-nb15-dataset) and place it in:

```
data/UNSW-NB15/UNSW_NB15_training-set.csv
```

### 3. Create the Sample Dataset

```python
import pandas as pd
df = pd.read_csv("data/UNSW-NB15/UNSW_NB15_training-set.csv")
sample = pd.concat([
    df[df['label']==0].sample(100, random_state=42),
    df[df['label']==1].sample(100, random_state=42)
])
sample.to_csv("data/UNSW-NB15/sample.csv", index=False)
```

### 4. Train the Models

Run the scikit-learn training script (this avoids PySpark ML save issues on Windows). It trains both classifiers and saves them as pickle files:

```bash
python scripts/train_models.py
```

This produces:

```
models/
├── binary_model.pkl               # Binary GBT model
├── multiclass_model.pkl           # Multiclass RF model
├── scaler.pkl                     # StandardScaler
├── unsw_label_mapping.json        # Attack type ID → name
└── unsw_training_results.json     # Training metrics
```

### 5. Start Infrastructure Services

```bash
docker compose up -d
```

Wait for all services to be healthy:

```bash
# Check Cassandra
docker exec nids_cassandra cqlsh -e "describe keyspaces"

# Check Redis
docker exec nids_redis redis-cli ping

# Check Kafka
docker logs nids_kafka --tail 5
```

### 6. Run Tests

```bash
pytest tests/ -v
```

---

## How to Run the Full Pipeline (Manual Steps)

You need **multiple terminal windows** (ensure your virtual environment is activated in each):

### 1. Start Infrastructure Services

Before running the application, start Cassandra, Redis, and Kafka:

```bash
# Using the run script (includes wait loops)
bash run.sh

# OR using docker compose directly
docker compose up -d
```

### 2. Start the Dashboard (Terminal 1)

```bash
.\venv\Scripts\Activate.ps1
python -m dashboard.app
```
Open **http://localhost:5000** in your browser.

### 3. Start the Streaming Pipeline (Terminal 2)

```bash
.\venv\Scripts\Activate.ps1
python -m streaming.pipeline_runner
```
This connects to Kafka, loads the trained GBT (binary) and RF (multiclass) models automatically, and waits for incoming data.

**What happens inside the pipeline:**
1. Reads JSON messages from Kafka topic `network-traffic`
2. **Binary inference** (GBTClassifier): classifies each row as Normal (0) or Attack (1)
3. For rows predicted as Attack → **Multiclass inference** (RandomForestClassifier): predicts the specific attack type (DoS, Exploits, Fuzzers, etc.)
4. Stores detected attacks in **Cassandra** (durable) + **Redis** (fast cache)
5. The dashboard reads from Redis for live updates

### 4. Start the Kafka Producer (Terminal 3)

```bash
.\venv\Scripts\Activate.ps1

# Stream the default datasets sequentially (UNSW-NB15_1.csv through 4.csv)
python kafka_producer.py --data-source unsw

# Limit the rate (e.g., 500 rows per second)
python kafka_producer.py --data-source unsw --rate 500

# Loop continuously indefinitely
python kafka_producer.py --data-source unsw --loop

# Stream a specific file
python kafka_producer.py --data-source unsw --file data/UNSW-NB15/UNSW_NB15_training-set.csv
```

### Stub Mode (No Trained Models)

If you don't have trained models yet, run the pipeline in stub mode:

```bash
$env:STUB_MODELS = "true"
python -m streaming.pipeline_runner
```

This generates fake predictions for testing the infrastructure.

---

## How to Demo Each Component

### 🔴 Demo: Cassandra (Persistent Storage)

Cassandra stores every alert permanently. Show this during your demo:

```bash
# Connect to Cassandra
docker exec -it nids_cassandra cqlsh
```

Inside `cqlsh`:

```sql
-- Show the keyspace and tables
DESCRIBE KEYSPACE nids;

-- Count total alerts
SELECT COUNT(*) FROM nids.alerts;

-- View recent alerts for a session (replace session-id)
SELECT alert_time, attack_type, severity, src_ip, dst_ip
FROM nids.alerts
WHERE session_id = 'local-session'
LIMIT 10;

-- Show all sessions
SELECT * FROM nids.sessions;

-- Show alerts by specific attack type
SELECT alert_time, attack_type, binary_probability, attack_confidence
FROM nids.alerts
WHERE session_id = 'local-session'
LIMIT 20;
```

**Key talking points:**
- Cassandra uses **wide-column storage** — partition key is `session_id`, clustering key is `alert_time DESC`
- This means all alerts for one session are stored together, sorted by time — perfect for "show me the latest alerts"
- Cassandra can handle **millions of writes/sec** — critical for a real-time IDS that might see thousands of network packets per second
- Data survives container restarts (uses a Docker volume `cassandra_data`)

### 🔵 Demo: Redis (Fast Cache + Pub/Sub)

Redis is the speed layer between the pipeline and the dashboard:

```bash
# Connect to Redis
docker exec -it nids_redis redis-cli
```

Inside `redis-cli`:

```bash
# See all Redis keys
KEYS nids:*

# Check how many alerts are cached for a session
LLEN nids:alerts:local-session

# Read the 5 most recent cached alerts (JSON)
LRANGE nids:alerts:local-session 0 4

# Check session metadata
HGETALL nids:sessions

# Monitor live alert flow in real-time (leave this open during demo!)
# Every time the pipeline stores an alert, you'll see it here
MONITOR
```

**Key talking points:**
- Redis stores alerts as a **list** (`LPUSH` + `LTRIM` to cap at 10,000) — O(1) inserts
- The dashboard reads from Redis with `LRANGE` — **sub-millisecond** response time
- Redis acts as a **write-through cache**: alerts go to both Cassandra AND Redis
- If Redis goes down, the system **degrades gracefully** — falls back to Cassandra, then in-memory

### 📊 Demo: Dashboard

Navigate through the 4 pages at **http://localhost:5000**:

1. **Dashboard** (`/`) — Live stat cards (total alerts, high/medium/low), severity doughnut chart, real-time alert feed
2. **Alerts** (`/alerts`) — Filterable by attack type and severity, sortable columns, shows source/destination IPs
3. **Analytics** (`/analytics`) — Bar chart of attack categories, timeline of alerts over time, ranked threat table
4. **Settings** (`/settings`) — Session management, service health status

### 🟢 Demo: Full End-to-End Flow

For the most impressive demo, show all components simultaneously:

1. Open **4 browser tabs**: Dashboard, Alerts, Analytics, Settings
2. Open a **terminal with `redis-cli MONITOR`** to show real-time cache writes
3. Open **cqlsh** in another terminal to query Cassandra
4. Start the **pipeline runner** in one terminal
5. Start the **Kafka producer** — watch alerts appear across all views simultaneously

---

## ML Pipeline Details

### Binary Classification (Stage 1)

- **Model:** Gradient Boosted Trees (GBTClassifier)
- **Task:** Normal traffic (0) vs Attack traffic (1)
- **Features:** 39 numeric features from UNSW-NB15
- **Preprocessing:** StandardScaler normalization
- **Expected metrics:** AUC ~0.97, Accuracy ~0.94

### Multiclass Classification (Stage 2)

- **Model:** Random Forest Classifier (100 trees)
- **Task:** Identify specific attack category (only runs on rows where binary prediction = Attack)
- **Categories:** Normal, DoS, Exploits, Fuzzers, Generic, Reconnaissance, Shellcode, Worms, Backdoors, Analysis
- **Expected metrics:** Weighted F1 ~0.70

### Two-Stage Design Rationale

1. **Efficiency:** Most traffic is normal — binary classifier quickly filters it out, avoiding expensive multiclass inference
2. **Accuracy:** Each model is specialized — the binary model maximizes detection rate, the multiclass model focuses on attack-only data
3. **Interpretability:** Dashboard can show both "is this an attack?" and "what type of attack?"

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Dashboard home page |
| `GET` | `/alerts` | Alerts page |
| `GET` | `/analytics` | Analytics page |
| `GET` | `/settings` | Settings page |
| `GET` | `/api/health` | Service health check |
| `GET` | `/api/alerts?limit=100&attack_type=DoS` | Fetch alerts (filterable) |
| `GET` | `/api/alerts/recent?limit=20` | Recent alerts for dashboard feed |
| `GET` | `/api/alerts/stats?hours=24` | Aggregate stats (by severity, by type) |
| `GET` | `/api/alerts/timeline?hours=24&interval=60` | Time-bucketed alert counts |
| `GET` | `/api/attack-types` | Attack type mapping |
| `GET` | `/api/alerts/by-type/<type>` | Alerts filtered by attack type |
| `GET` | `/api/sessions` | List sessions |
| `GET` | `/api/session/current` | Current session ID |
| `POST` | `/api/session/set` | Switch session |
| `POST` | `/api/session/new` | Create new session |
| `DELETE` | `/api/session/delete` | Delete a session |
| `DELETE` | `/api/sessions/delete-all` | Delete all sessions |

---

## CI/CD

The project includes a full Jenkins pipeline (see `Jenkinsfile` and [CICD.md](CICD.md)):

```
Checkout → Install Deps → Lint (flake8) → Test (pytest) → Build (Docker) → Deploy
```

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `No module named pyspark` | Activate venv: `.\venv\Scripts\Activate.ps1` then `pip install -r requirements.txt` |
| `Java not found` | Install Java 11+ and set `JAVA_HOME` |
| Cassandra won't start | Make sure Docker has enough RAM (4GB+). Check: `docker logs nids_cassandra` |
| Kafka connection refused | Wait 30s after `docker compose up`. Check: `docker logs nids_kafka` |
| `STUB_MODELS` fallback | Models not found — run `unsw_model_training.ipynb` first |
| Dashboard shows 0 alerts | Make sure all 3 terminals are running (dashboard, pipeline, producer) |
| Redis connection error | System degrades gracefully to Cassandra → in-memory. Check Redis: `docker exec nids_redis redis-cli ping` |