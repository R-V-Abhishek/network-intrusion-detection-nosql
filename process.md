Here's the full timeline. All three work simultaneously after Day 1.

---

## Pre-Day 1 — Setup (Everyone, 30 mins before first meeting)

Each person:
1. Clone the repo
2. Create and activate venv: `python -m venv venv` → Activate.ps1
3. Install current deps: `pip install -r requirements.txt`
4. Download UNSW-NB15 raw CSVs into UNSW-NB15
5. Verify they can open unsw_model_training.ipynb without errors
6. Verify tests run: `pytest tests/ -v` — all should pass (these test config only, no services needed)

> **CI/CD note:** Jenkins, `Jenkinsfile`, `tests/`, and `docker-compose.ci.yml` are already committed to `master`. See [CICD.md](CICD.md) for full setup guide.

---

## Day 1 — Joint Session (All 3 together, ~2 hours)

### Checkpoint 1.1 — Agree on schema (30 mins)
All three open unsw_feature_names.json together and verify the 39 feature names match the actual CSV columns. Lock them. No one changes this file after today.

### Checkpoint 1.2 — Slice sample (Person 1 shares screen, 15 mins)
Person 1 runs this live:
```python
import pandas as pd
df = pd.read_csv("data/UNSW-NB15/UNSW_NB15_training-set.csv")
sample = pd.concat([
    df[df['label']==0].sample(100, random_state=42),
    df[df['label']==1].sample(100, random_state=42)
])
sample.to_csv("data/UNSW-NB15/sample.csv", index=False)
```
Everyone pulls `sample.csv` immediately. This is **everyone's test input for all local dev**.

### Checkpoint 1.3 — Scaffold new file structure (Person 3 shares screen, 30 mins)
Person 3 creates these empty files with just docstrings and `pass`, commits to `main`:
```
streaming/binary_inference.py
streaming/multiclass_inference.py
streaming/pipeline_runner.py
dashboard/api_alerts.py
dashboard/api_analytics.py
```

### Checkpoint 1.4 — Add STUB_MODELS guard (Person 3, 15 mins)
Person 3 adds this to `streaming/pipeline_runner.py` and commits:
```python
STUB_MODELS = os.getenv("STUB_MODELS", "false").lower() == "true"
```
Person 1 and 2 will reference `STUB_MODELS` from `pipeline_runner` until their models are ready.

### Checkpoint 1.5 — Branch off (All 3, 10 mins)
```bash
# Person 1
git checkout -b feature/p1-ingestion-binary

# Person 2
git checkout -b feature/p2-classification-analytics

# Person 3
git checkout -b feature/p3-infra-storage
```

**After this point, all three work independently and in parallel.**

### Checkpoint 1.6 — Verify CI pipeline is live (Person 3, 10 mins)
Person 3 opens Jenkins → confirms the `master` branch pipeline ran successfully after the `Jenkinsfile` commit. Everyone should see a green build before branching off. If it's red, fix it before Day 2 starts.

Jenkins build URL (once set up): `http://<jenkins-server>:8080/job/nids-pipeline/`

---

## Week 1 — Core Build

---

### Person 1 — Days 2–4

#### Checkpoint P1-1 (Day 2 morning) — Write `preprocessing_utils.py`
Functions needed and their signatures, agree with P2 since they import this:
```python
def clip_outliers(df, cols, lower=0.01, upper=0.99) -> pd.DataFrame
def encode_labels(df, col) -> Tuple[pd.DataFrame, dict]
def validate_schema(df, expected_cols: list) -> bool
def split_train_test(df, test_size=0.2, stratify_col='label') -> Tuple
```
Commit: `"Add preprocessing utilities with clip, encode, validate, split"`

#### Checkpoint P1-2 (Day 2 afternoon) — Write `preprocess_unsw_nb15.py`
Steps inside the script in order:
1. Load all UNSW CSVs from UNSW-NB15
2. Drop columns: `id`, `attack_cat` (Person 2 owns that column)
3. Call `validate_schema(df, UNSW_FEATURE_NAMES)` — import `unsw_feature_names.json`
4. Handle nulls: drop rows where null > 50% of columns, fill numeric nulls with median
5. Call `clip_outliers()` on all numeric columns
6. Call `split_train_test()` with `stratify_col='label'`
7. Save: `data/preprocessed/unsw_train.parquet`, `data/preprocessed/unsw_test.parquet`

Commit: `"Add UNSW-NB15 preprocessing pipeline"`

Test locally:
```bash
python scripts/preprocess_unsw_nb15.py
# Expected: data/preprocessed/unsw_train.parquet created, check row count printed
```

#### Checkpoint P1-3 (Day 3 morning) — Write `run_preprocessing.py`
```bash
python scripts/run_preprocessing.py --dataset unsw --output data/preprocessed/
```
Validates output schema after saving. Post in team chat: **"Preprocessed Parquet ready, pull and test"**.

Commit: `"Add CLI runner for preprocessing"`

#### Checkpoint P1-4 (Day 3 afternoon) — Write binary training cells in `unsw_model_training.ipynb`
Cells to write/own:
1. Load `data/preprocessed/unsw_train.parquet` into Spark DataFrame
2. `VectorAssembler` → assemble features using `UNSW_FEATURE_CONFIG["numeric_features"]`
3. `StandardScaler` → fit, save to unsw_nb15_scaler
4. Train `GBTClassifier(labelCol='label', maxIter=20)` → evaluate on test set → AUC, accuracy
5. Train `RandomForestClassifier(labelCol='label', numTrees=100)` → compare
6. Save best model to unsw_gbt_binary_classifier
7. Write metrics to unsw_training_results.json:
```json
{
  "binary": {
    "model": "GBTClassifier",
    "accuracy": 0.94,
    "auc": 0.97,
    "f1": 0.93
  }
}
```

Commit: `"Train and save UNSW binary classifier, AUC=0.97"`

#### Checkpoint P1-5 (Day 4) — Write `streaming/binary_inference.py`
```python
def load_binary_model(model_path, scaler_path) -> Tuple[model, scaler]
def assemble_features(df: DataFrame, feature_cols: list) -> DataFrame
def apply_binary_inference(df: DataFrame, model, scaler) -> DataFrame
    # returns df with new columns: features_vec, binary_prediction, binary_probability
```
Use `sample.csv` to test:
```python
# At bottom of file, under if __name__ == "__main__":
df = spark.read.csv("data/UNSW-NB15/sample.csv", header=True, inferSchema=True)
result = apply_binary_inference(df, *load_binary_model(...))
result.select("binary_prediction", "binary_probability").show(5)
```

Commit: `"Add binary inference module with standalone test"`

Post in team chat: **"binary_inference.py ready, P3 can now wire it into pipeline_runner"**

---

### Person 2 — Days 2–4

#### Checkpoint P2-1 (Day 2 morning) — Write all of config.py
The most critical file — everyone imports from it. Write in this order:
1. `KAFKA_CONFIG` — bootstrap servers, topic names
2. `SPARK_CONFIG` — app name, master, memory, packages
3. `UNSW_FEATURE_CONFIG` — 39 numeric features, label column
4. `UNSW_ATTACK_TYPE_MAPPING` — integer → string label dict:
```python
UNSW_ATTACK_TYPE_MAPPING = {
    0: "Normal", 1: "Fuzzers", 2: "Analysis", 3: "Backdoors",
    4: "DoS", 5: "Exploits", 6: "Generic", 7: "Reconnaissance",
    8: "Shellcode", 9: "Worms"
}
```
5. `MODEL_PATHS` — all UNSW model dirs
6. `STREAMING_CONFIG`, `ALERT_CONFIG`, `PRODUCER_CONFIG`

Commit: `"Add full config for UNSW pipeline"` — **notify team immediately**, everyone needs this.

#### Checkpoint P2-2 (Day 2 morning, after P2-1) — Write __init__.py and scaler_paths.py
Make sure all symbols are exported. Commit: `"Export all config symbols"`

#### Checkpoint P2-3 (Day 2 afternoon) — Write `label_harmonization.ipynb`
Cells:
1. Load UNSW_NB15_training-set.csv
2. Get `attack_cat` unique values
3. Build deterministic int mapping (sort alphabetically → assign 0–N)
4. Add `attack_cat_id` column to DataFrame
5. Save mapping to unsw_label_mapping.json
6. Verify: `Normal` → 0, rest alphabetically assigned

Commit: `"Add label harmonization notebook, generate label mapping JSON"`

Post in team chat: **"unsw_label_mapping.json committed, P1 preprocess can now include cat labels if needed"**

#### Checkpoint P2-4 (Day 3) — Write multiclass training cells in `unsw_model_training.ipynb`
Cells to own (separate section from P1's binary cells):
1. Load `data/preprocessed/unsw_train.parquet`
2. Load scaler from unsw_nb15_scaler — **reuse P1's scaler, don't retrain it**
3. Filter to attack rows only (`label == 1`)
4. `VectorAssembler` on same 39 features
5. Train `RandomForestClassifier(labelCol='attack_cat_id', numTrees=100, numClasses=10)`
6. Evaluate: per-class precision, recall, F1 using `MulticlassClassificationEvaluator`
7. Save to unsw_rf_multiclass_classifier
8. Append to unsw_training_results.json:
```json
{
  "multiclass": {
    "model": "RandomForestClassifier",
    "accuracy": 0.72,
    "weighted_f1": 0.70,
    "per_class": { "DoS": 0.85, "Reconnaissance": 0.78, ... }
  }
}
```

Commit: `"Train and save UNSW multiclass classifier"`

#### Checkpoint P2-5 (Day 4 morning) — Write `streaming/multiclass_inference.py`
```python
def load_multiclass_model(model_path) -> model
def apply_multiclass_inference(df: DataFrame, model, label_mapping: dict) -> DataFrame
    # Only runs on rows where binary_prediction == 1
    # Adds: attack_cat_id, attack_type (string), attack_confidence
```

Commit: `"Add multiclass inference module"`

Post to team: **"multiclass_inference.py ready, P3 can wire into pipeline_runner"**

#### Checkpoint P2-6 (Day 4 afternoon) — Write `dashboard/api_analytics.py`
Endpoints to implement:
- `GET /api/alerts/stats?hours=24&session_id=X` — total, by severity, by attack type
- `GET /api/alerts/timeline?hours=24&interval=60` — time-bucketed counts
- `GET /api/attack-types` — return `UNSW_ATTACK_TYPE_MAPPING` dict
- `GET /api/alerts/by-type/<attack_type>` — filtered list

Commit: `"Add analytics API endpoints"`

#### Checkpoint P2-7 (Day 4 afternoon) — Write visualization.ipynb
Plots to produce:
1. Confusion matrix for binary classifier
2. Confusion matrix for multiclass classifier
3. Per-class ROC curves
4. Feature importance bar chart (top 20 features)
5. Attack category distribution pie chart

Commit: `"Add evaluation visualization notebook"`

---

### Person 3 — Days 2–4

#### Checkpoint P3-1 (Day 2 morning) — Update docker-compose.yml
Remove MongoDB + Mongo-Express. Add:
- `cassandra:4.1` with healthcheck (`cqlsh -e "describe keyspaces"`)
- `redis:7.2-alpine` with `maxmemory 256mb`
- `redislabs/redisinsight` on port 5540
- `ipushc/cassandra-web` on port 8081

Update Dockerfile.spark:
```
RUN pip install cassandra-driver redis
```

Update requirements.txt: add `cassandra-driver>=3.29.0`, `redis>=5.0.0`

Commit: `"Replace MongoDB with Cassandra+Redis in docker-compose"`

Test: `docker compose up cassandra redis -d` → verify both healthy

#### Checkpoint P3-2 (Day 2 afternoon) — Write cassandra-init.cql
Tables needed:
- `intrusion_alerts` — partition key: `session_id`, clustering: `alert_time DESC`
- `sessions` — partition key: `session_id`
- `alert_stats_by_session` — counter table for fast stats queries

Commit: `"Add Cassandra schema: alerts + sessions + stats counter table"`

Test: `docker exec -it nids-cassandra cqlsh -f /docker-entrypoint-initdb.d/cassandra-init.cql`

#### Checkpoint P3-3 (Day 3 morning) — Write alert_storage.py
Classes and methods to implement:

```python
class AlertStorage:
    def connect(self, max_retries=5) -> bool
        # Cassandra cluster connect with retry loop
    def store_alert(self, alert: dict, session_id: str) -> str
        # INSERT INTO intrusion_alerts ...
        # Also: ZADD redis nids:recent_alerts <timestamp> <json>
        # Also: PUBLISH redis nids:alerts <json>
    def get_alerts(self, session_id, limit=100, attack_type=None) -> list
        # SELECT FROM intrusion_alerts WHERE session_id=? ORDER BY alert_time DESC
    def get_stats(self, session_id, hours=24) -> dict
        # Query alert_stats_by_session counter table
    def get_timeline(self, session_id, hours=24, interval_mins=60) -> list
        # Bucket alerts by time interval from recent_alerts sorted set
    def register_session(self, session_id, dataset) -> None
    def get_sessions(self, limit=10) -> list
    def delete_session(self, session_id) -> dict
    def delete_all_sessions(self) -> dict
    def close(self) -> None

# Module-level session helpers (same API as original)
def start_new_session() -> str
def get_current_session_id() -> str
def set_current_session_id(session_id: str) -> None
def clear_session() -> None
```

Commit: `"Add Cassandra+Redis alert storage with full session management"`

Post to team: **"alert_storage.py ready — same API as before, P1/P2 inference modules can use it"**

#### Checkpoint P3-4 (Day 3 afternoon) — Write `streaming/pipeline_runner.py`
This is the main entrypoint that wires everything together:

```python
def create_spark_session() -> SparkSession
def build_kafka_stream(spark, topic) -> DataFrame
def run_pipeline(data_source="unsw", session_id=None):
    spark = create_spark_session()
    stream_df = build_kafka_stream(spark, KAFKA_CONFIG["topic"])
    session_id = start_new_session()
    
    def process_batch(batch_df, batch_id):
        if STUB_MODELS:
            # stub predictions
        else:
            batch_df = apply_binary_inference(batch_df, binary_model, scaler)
            batch_df = apply_multiclass_inference(batch_df, mc_model, label_map)
        
        alerts = extract_attack_rows(batch_df)
        storage.store_alert(alert, session_id)  # loops
    
    stream_df.writeStream.foreachBatch(process_batch).start().awaitTermination()
```

Commit: `"Add pipeline runner orchestrating Kafka→inference→storage"`

Test with stubs: `STUB_MODELS=true python -m streaming.pipeline_runner`

#### Checkpoint P3-5 (Day 4 morning) — Write app.py
Endpoints to implement:
- `GET /` → render `dashboard.html`
- `GET /api/health` → ping Cassandra + Redis, return status JSON
- `GET /api/sessions` → `storage.get_sessions()`
- `GET /api/session/current` → return `get_current_session_id()`
- `POST /api/session/set` → `set_current_session_id(id)`
- `DELETE /api/session/delete` → `storage.delete_session(id)`
- `DELETE /api/sessions/delete-all` → `storage.delete_all_sessions()`
- Register `api_alerts` and `api_analytics` blueprints

Commit: `"Add Flask app with session management and blueprint registration"`

#### Checkpoint P3-6 (Day 4 afternoon) — Write HTML templates and run.sh

Templates to write:
- `base.html` — nav, sidebar, WebSocket JS client that subscribes to Redis channel via SSE
- `settings.html` — session list with delete buttons, service health status table

Update run.sh:
```bash
docker compose up --build -d
echo "Waiting for Cassandra..."
until docker exec nids-cassandra cqlsh -e "describe keyspaces" > /dev/null 2>&1; do sleep 5; done
echo "Waiting for Kafka..."
until docker exec nids-kafka kafka-topics --bootstrap-server localhost:9092 --list > /dev/null 2>&1; do sleep 5; done
echo ""
echo "All services ready:"
echo "  Kafka UI:        http://localhost:8080"
echo "  Cassandra Web:   http://localhost:8081"
echo "  Redis Insight:   http://localhost:5540"
echo "  Dashboard:       http://localhost:5000"
```

Commit: `"Add base template, settings page, and run.sh with healthcheck"`

---

## Week 2 — Integration

### Checkpoint INT-1 (Day 5 morning) — P1 + P3 sync
P3 replaces `STUB_MODELS` binary block with real call:
```python
from streaming.binary_inference import load_binary_model, apply_binary_inference
binary_model, scaler = load_binary_model(MODEL_PATHS["unsw_gbt_binary"], MODEL_PATHS["unsw_nb15_scaler"])
```
Test together: `docker compose up -d` → run producer on `sample.csv` → verify alerts appear in Cassandra.

Commit by P3: `"Wire real binary model into pipeline runner"`

### Checkpoint INT-2 (Day 5 afternoon) — P2 + P3 sync
P3 replaces multiclass stub:
```python
from streaming.multiclass_inference import load_multiclass_model, apply_multiclass_inference
mc_model = load_multiclass_model(MODEL_PATHS["unsw_multiclass"])
```
Test: send 100 rows where `label=1` → verify `attack_type` column populated in Cassandra.

Commit by P3: `"Wire real multiclass model into pipeline runner"`

### Checkpoint INT-3 (Day 6) — P1 + P2 + P3 dashboard end-to-end
All three on a call:
1. `docker compose up -d` — full stack
2. Person 1 runs: `python kafka_producer.py --data-source unsw --rate 500`
3. Person 3 runs: `python -m streaming.pipeline_runner`
4. All three verify dashboard at `http://localhost:5000`:
   - Dashboard page shows live alert count
   - Analytics page shows attack type breakdown
   - Alerts page shows per-row table with `attack_type` populated

Fix any integration bugs. Whoever finds the bug fixes it. Commit on their own branch.

### Checkpoint INT-4 (Day 6 afternoon) — Person 2 writes analytics.html
Now that real multiclass data is flowing, wire up:
- Chart.js bar chart for attack category counts from `/api/alerts/stats`
- Timeline line chart from `/api/alerts/timeline`
- Top threats table

Commit: `"Add analytics template with live attack category charts"`

### Checkpoint INT-5 (Day 7) — Person 1 writes alerts.html and `dashboard.html`
Wire up:
- `dashboard.html`: total alert count, live feed (SSE from Redis channel), threat severity gauge
- `alerts.html`: sortable table, filter by severity/attack type dropdowns

Commit: `"Add dashboard and alerts templates with live SSE feed"`

---

## Week 2 End — PR Review Prep

### Checkpoint PR-1 (Day 8) — Each person cleans their branch

Each person runs:
```bash
git diff main --stat        # review what you're contributing
git log --oneline           # verify commit history is clean
```

Each person writes their PR description with:
- Modules they own
- How to test their piece in isolation
- Link to the relevant checkpoint in this timeline

### Checkpoint PR-2 (Day 8–9) — PRs open

All three PRs open simultaneously. **Jenkins automatically runs the full pipeline on each PR branch** (Checkout → Install → Lint → Test → Build). A PR cannot be merged until Jenkins shows a green build.

Project head reviews using:

| For Person 1 | For Person 2 | For Person 3 |
|---|---|---|
| `python scripts/run_preprocessing.py` runs without error | unsw_training_results.json has AUC ≥ 0.85 | `docker compose up` goes fully healthy |
| `data/preprocessed/unsw_train.parquet` has correct schema | visualization.ipynb renders all plots | `/api/health` returns 200 with Cassandra + Redis status |
| `binary_inference.py` standalone test prints predictions | `multiclass_inference.py` test prints attack type labels | Producer → Streaming → Dashboard shows live alerts |
| Jenkins build green on PR branch | Jenkins build green on PR branch | Jenkins build green on PR branch |

### Checkpoint PR-3 (Day 9–10) — Merge to main

Order: P1 → P2 → P3 (in this order only to avoid pipeline_runner merge conflicts — everything else can merge in any order). After each merge, the other two rebase their branch: `git rebase main`.

### Checkpoint FINAL (Day 10) — Tag release

```bash
git tag -a v1.0.0 -m "UNSW-NB15 NIDS - binary + multiclass, Cassandra + Redis"
git push origin v1.0.0
```

Jenkins will run one final build on `master` after the tag push. Confirm the Deploy stage completes successfully.

---

## Full Timeline at a Glance

```
Day 0   [P3]     Jenkins setup, Jenkinsfile + tests/ committed to master → CI live
Day 1   [ALL]    Joint setup, sample.csv, scaffold, branch off, verify CI green
Day 2   [P1]     preprocessing_utils.py, preprocess_unsw_nb15.py
        [P2]     config.py, config/__init__.py, label_harmonization.ipynb
        [P3]     docker-compose.yml (Cassandra+Redis), cassandra-init.cql
Day 3   [P1]     run_preprocessing.py, binary training notebook
        [P2]     multiclass training notebook
        [P3]     alert_storage.py (Cassandra + Redis)
Day 4   [P1]     binary_inference.py
        [P2]     multiclass_inference.py, api_analytics.py, visualization.ipynb
        [P3]     pipeline_runner.py, dashboard/app.py
Day 5   [P1+P3]  Wire binary model → pipeline_runner, test with producer
        [P2+P3]  Wire multiclass model → pipeline_runner
Day 6   [ALL]    Full end-to-end integration test, analytics.html
Day 7   [P1]     alerts.html + dashboard.html final polish
        [P3]     base.html, settings.html, run.sh
Day 8   [ALL]    Branch cleanup, PR descriptions, Jenkins green on all branches
Day 9   [HEAD]   Review + approve PRs (Jenkins gate must be green to merge)
Day 10  [ALL]    Merge, rebase, tag v1.0.0, confirm Jenkins Deploy stage passes
```