# Integration Guide — Week 2 Handoff

> **Date:** March 9, 2026  
> **Current position in timeline:** INT-1 (Week 2 integration begins)  
> **Branch merge order:** P1 → P2 → P3 (strictly in this order to avoid pipeline_runner conflicts)

---

## What Has Been Completed

| Checkpoint | Owner | Status |
|---|---|---|
| 1.1 — `unsw_feature_names.json` locked | All | ✅ Done |
| 1.2 — `sample.csv` sliced (201 rows) | P1 | ✅ Done |
| 1.3 — Scaffold files with docstrings | P3 | ✅ Done |
| 1.4 — `STUB_MODELS` guard in `pipeline_runner.py` | P3 | ✅ Done |
| 1.5 — All three branched off | All | ✅ Done |
| P1-1 — `src/preprocessing_utils.py` | P1 | ✅ Done |
| P1-2 — `scripts/preprocess_unsw_nb15.py` | P1 | ✅ Done |
| P1-3 — `scripts/run_preprocessing.py` CLI | P1 | ✅ Done |
| P1-4 — Binary training cells in notebook | P1 | ✅ Done |
| P1-5 — `streaming/binary_inference.py` | P1 | ✅ Done |
| P2-1 — `config/config.py` | P2 | ✅ Done |
| P2-2 — `config/__init__.py` | P2 | ✅ Done |
| P2-3 — `label_harmonization.ipynb` + `unsw_label_mapping.json` | P2 | ✅ Done |
| P2-4 — Multiclass training cells in notebook | P2 | ✅ Done |
| P2-5 — `streaming/multiclass_inference.py` | P2 | ✅ Done |
| P2-6 — `dashboard/api_analytics.py` endpoints | P2 | ✅ Done |
| P2-7 — `visualization.ipynb` | P2 | ✅ Done |
| P3-1 — `docker-compose.yml` (Cassandra + Redis) | P3 | ✅ Done |
| P3-2 — `cassandra-init.cql` schema | P3 | ✅ Done |
| P3-3 — `alert_storage.py` (Cassandra + Redis) | P3 | ✅ Done |
| P3-4 — `streaming/pipeline_runner.py` (real models wired) | P3 | ✅ Done |
| P3-5 — `dashboard/app.py` | P3 | ✅ Done |
| P3-6 — `base.html`, `settings.html`, `run.sh` | P3 | ✅ Done |
| Models trained on disk | P1 + P2 | ✅ Done |
| `kafka_producer.py` created | P1 | ✅ Done |
| Scaler folder renamed → `unsw_nb15_scaler` | P1 | ✅ Done |

---

## Remaining Work by Person

---

## Person 1 (P1) — Ingestion & Binary

### Immediate: Open your PR

Your branch `feature/p1-ingestion-binary` is pushed and up to date. Open the PR on GitHub now.

**PR title:** `[P1] Preprocessing pipeline + binary inference + Kafka producer`

**PR description to include:**
```
Modules owned:
- src/preprocessing_utils.py      — clip_outliers, encode_labels, validate_schema, split_train_test
- scripts/preprocess_unsw_nb15.py — full UNSW-NB15 preprocessing pipeline
- scripts/run_preprocessing.py    — CLI runner (--dataset unsw --output data/preprocessed/)
- streaming/binary_inference.py   — GBT binary classifier inference module
- kafka_producer.py               — Kafka producer with --rate and --loop flags

How to test in isolation:
  pip install -r requirements.txt
  python scripts/run_preprocessing.py --dataset unsw --output data/preprocessed/
  python streaming/binary_inference.py   # requires trained models in models/

Scaler path fix: models/unsw_scaler renamed to models/unsw_nb15_scaler (matches config.py MODEL_PATHS).
```

**Once your PR is merged to master → notify P2 and P3 immediately.**

---

### INT-1 Test (P1 + P3 together, after P1's PR is merged)

After P3 has rebased onto master, run the test together:

```bash
# Terminal 1 — P3 runs the pipeline
docker compose up -d
python -m streaming.pipeline_runner

# Terminal 2 — P1 runs the producer
pip install kafka-python
python kafka_producer.py --data-source unsw --rate 10 --loop
```

**Verify success:**
```bash
docker exec -it nids-cassandra cqlsh -e \
  "SELECT alert_time, attack_type, binary_probability FROM nids.intrusion_alerts LIMIT 10;"
```
Rows with `binary_probability > 0` should appear. `attack_type` will be `Unknown` at this stage — that is expected until INT-2.

---

### INT-5 (Day 7) — Write `alerts.html` and `dashboard.html`

After INT-3 (full end-to-end working), build the two frontend templates.

**`templates/alerts.html`** — wire up:
- Sortable table of alerts (columns: `alert_time`, `src_ip`, `dst_ip`, `protocol`, `attack_type`, `severity`, `binary_probability`)
- Filter dropdowns: severity, attack_type
- Data source: `GET /api/alerts?session_id=X&limit=100`

**`templates/dashboard.html`** — wire up:
- Total alert count card
- Live alert feed via SSE (subscribe to Redis pub/sub channel `nids:alerts` through a `/api/stream` endpoint)
- Threat severity gauge (critical / high / medium)
- Data sources: `GET /api/alerts/stats?hours=24&session_id=X`

Use the `base.html` already written by P3 as the layout template.

Commit: `"Add dashboard and alerts templates with live SSE feed"`

---

### PR Cleanup Checklist (Day 8)

```bash
git diff main --stat        # review what you're contributing
git log --oneline           # verify commit history is clean
```

---

## Person 2 (P2) — Classification & Analytics

### Immediate: Open your PR (after P1's PR is merged to master)

**Branch:** `feature/p2-classification-analytics`

```bash
git fetch origin
git rebase origin/master     # rebase onto freshly merged P1 work
git push origin feature/p2-classification-analytics --force-with-lease
```

**PR title:** `[P2] Config, multiclass inference, analytics API, visualizations`

**PR description to include:**
```
Modules owned:
- config/config.py               — KAFKA_CONFIG, SPARK_CONFIG, UNSW_FEATURE_CONFIG,
                                   UNSW_ATTACK_TYPE_MAPPING, MODEL_PATHS, ALERT_CONFIG, PRODUCER_CONFIG
- config/__init__.py             — exports all config symbols
- streaming/multiclass_inference.py  — RandomForest multiclass inference (attack rows only)
- dashboard/api_analytics.py     — /api/alerts/stats, /api/alerts/timeline, /api/attack-types, /api/alerts/by-type/<type>
- label_harmonization.ipynb      — generates unsw_label_mapping.json
- visualization.ipynb            — confusion matrices, ROC curves, feature importance

How to test:
  python -c "from config.config import MODEL_PATHS; print(MODEL_PATHS)"
  python streaming/multiclass_inference.py   # requires trained models
```

**Notify P3 when merged.**

---

### INT-2 Test (P2 + P3 together, after P2's PR is merged)

After P3 rebases again onto master with P2's code:

```bash
# Terminal 1 — restart pipeline
python -m streaming.pipeline_runner

# Terminal 2 — send attack rows only
# Edit kafka_producer.py run to filter label==1 from sample.csv, or just:
python kafka_producer.py --data-source unsw --file data/UNSW-NB15/sample.csv --rate 10 --loop
```

**Verify success:**
```bash
docker exec -it nids-cassandra cqlsh -e \
  "SELECT attack_type, attack_confidence FROM nids.intrusion_alerts WHERE binary_prediction=1 LIMIT 10 ALLOW FILTERING;"
```
`attack_type` column must now show actual attack category strings (e.g. `Generic`, `DoS`, `Reconnaissance`) — not `Unknown`.

---

### INT-4 (Day 6 afternoon) — Write `analytics.html`

After INT-3 (full stack working with real data flowing):

**`templates/analytics.html`** — wire up:
- **Bar chart** — attack category counts from `GET /api/alerts/stats?hours=24&session_id=X`
  - Use Chart.js: `type: 'bar'`, labels = attack type names, data = counts per type
- **Timeline line chart** — from `GET /api/alerts/timeline?hours=24&interval=60`
  - X axis: time buckets (hourly), Y axis: alert count
- **Top threats table** — top 5 attack types by count with percentage

All charts must live-refresh every 30 seconds using `setInterval` + `fetch`.

Commit: `"Add analytics template with live attack category charts"`

---

### PR Cleanup Checklist (Day 8)

```bash
git diff main --stat
git log --oneline
```

Reviewer will check: `unsw_training_results.json` has AUC ≥ 0.85, `visualization.ipynb` renders all 5 plots without error.

---

## Person 3 (P3) — Infrastructure & Storage

### After P1's PR merges — rebase and verify INT-1 ready

```bash
git checkout feature/p3-infra-storage
git fetch origin
git rebase origin/master
```

Resolve any conflicts (most likely in `requirements.txt` — keep all packages from both branches).

```bash
git push origin feature/p3-infra-storage --force-with-lease
```

---

### INT-1 Test (with P1)

```bash
docker compose up -d

# Verify services healthy before starting pipeline:
docker compose ps      # all should show "healthy" or "running"

# Start pipeline:
python -m streaming.pipeline_runner
```

In a separate terminal (P1 runs this):
```bash
python kafka_producer.py --data-source unsw --rate 10 --loop
```

**Commit after passing:** `"Wire real binary model into pipeline runner"`
(Note: `pipeline_runner.py` already has the real imports — confirm they work; no code change expected unless a path issue surfaces.)

---

### After P2's PR merges — rebase again for INT-2

```bash
git fetch origin
git rebase origin/master
git push origin feature/p3-infra-storage --force-with-lease
```

**INT-2 test:** restart `pipeline_runner.py` and verify `attack_type` populates in Cassandra (see P2's section above).

**Commit after passing:** `"Wire real multiclass model into pipeline runner"`

---

### INT-3 — Full End-to-End (All three together, Day 6)

All three on a call. Steps:

```bash
# Step 1 — Bring up full stack
bash run.sh       # waits for Cassandra + Kafka healthchecks automatically

# Step 2 — P1 runs producer at load
python kafka_producer.py --data-source unsw --rate 500 --loop

# Step 3 — P3 runs pipeline
python -m streaming.pipeline_runner
```

All three open `http://localhost:5000` and verify:
- `/` (dashboard) — shows live incrementing alert count
- `/analytics` — shows attack type bar chart populated
- `/alerts` — shows per-row table with `attack_type` column filled

Fix bugs on whoever's branch introduced the issue. Commit with clear message referencing INT-3.

---

### Open your PR (after P2 merges, last in order)

**Branch:** `feature/p3-infra-storage`

```bash
git fetch origin
git rebase origin/master
git push origin feature/p3-infra-storage --force-with-lease
```

**PR title:** `[P3] Cassandra+Redis storage, pipeline runner, Flask dashboard`

**PR description to include:**
```
Modules owned:
- docker-compose.yml           — Cassandra 4.1, Redis 7.2, RedisInsight, Cassandra-Web, Kafka, Spark
- cassandra-init.cql           — intrusion_alerts, sessions, alert_stats_by_session tables
- alert_storage.py             — AlertStorage class + module-level session helpers
- streaming/pipeline_runner.py — Kafka → binary inference → multiclass inference → Cassandra/Redis
- dashboard/app.py             — Flask app with all session management endpoints + blueprint registration
- templates/base.html          — nav, sidebar, SSE WebSocket JS client
- templates/settings.html      — session list, delete, health status table
- run.sh                       — full stack startup with Cassandra + Kafka healthchecks

How to test:
  docker compose up -d
  curl http://localhost:5000/api/health     # must return 200 with cassandra+redis OK
  STUB_MODELS=true python -m streaming.pipeline_runner   # stub smoke-test without models
```

Reviewer checks: `docker compose up` goes fully healthy, `/api/health` returns 200 with both backends OK, producer → pipeline → dashboard shows live alerts.

---

### PR Cleanup Checklist (Day 8)

```bash
git diff main --stat
git log --oneline
```

---

## Full Remaining Timeline

```
March 9  [P1]      Open PR → merge to master → notify team
         [P1+P3]   INT-1: producer + pipeline, verify binary alerts in Cassandra

March 10 [P2]      Rebase onto master, open PR → merge → notify P3
         [P2+P3]   INT-2: verify attack_type populated in Cassandra

March 11 [P3]      Final rebase, open PR
         [ALL]     INT-3: full end-to-end test at http://localhost:5000
         [P2]      INT-4: analytics.html (charts live with real data)

March 12 [P1]      INT-5: dashboard.html + alerts.html with SSE live feed
         [ALL]     PR cleanup, write PR descriptions

March 13 [HEAD]    Review + approve all 3 PRs
                   Merge order: P1 → P2 → P3
                   After each merge, others rebase: git rebase main

March 14 [ALL]     Tag release:
                   git tag -a v1.0.0 -m "UNSW-NB15 NIDS - binary + multiclass, Cassandra + Redis"
                   git push origin v1.0.0
```

---

## Service URLs (once `docker compose up` is healthy)

| Service | URL |
|---|---|
| Dashboard | http://localhost:5000 |
| Kafka UI | http://localhost:8080 |
| Cassandra Web | http://localhost:8081 |
| Redis Insight | http://localhost:5540 |

---

## Quick Reference — Key File Locations

| File | Owner | Purpose |
|---|---|---|
| `unsw_feature_names.json` | Locked (All) | 39 numeric feature names — do not modify |
| `models/unsw_label_mapping.json` | P2 | attack_cat string ↔ integer mapping |
| `models/unsw_training_results.json` | P1 + P2 | training metrics (AUC, F1, accuracy) |
| `config/config.py` | P2 | single source of truth for all paths, topics, mappings |
| `data/UNSW-NB15/sample.csv` | All | 201-row test input for all local dev |
| `data/preprocessed/unsw_train.parquet` | P1 | training data (generated by run_preprocessing.py) |
| `data/preprocessed/unsw_test.parquet` | P1 | test data |
