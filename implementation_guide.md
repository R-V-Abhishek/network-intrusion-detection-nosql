# NIDS DevOps Polish Plan

## Background

Project is a working Network Intrusion Detection System (NIDS) with:
- Kafka → Spark Streaming → Cassandra/Redis pipeline
- Flask dashboard with REST API
- 4 test files (unit + integration smoke)
- Jenkinsfile with 6-stage declarative pipeline

Goal: make it solid as a **DevOps portfolio project**.

---

## 1. Tests

### Current state
| File | Coverage | Issues |
|---|---|---|
| `test_config.py` | Good config validation | ✅ Fine |
| `test_pipeline.py` | Env-var + pandas filter logic | ✅ Fine |
| `test_dashboard_api.py` | Config/severity checks only — **no Flask test client used** | ⚠️ Misleading name |
| `test_integration_storage_smoke.py` | Opt-in, gated by `NIDS_RUN_INTEGRATION=1` | ✅ Fine |

### Changes needed

#### [MODIFY] `tests/test_dashboard_api.py`
- Currently claims to test Flask API but only tests config. Fix: add actual Flask test client tests using `create_app()` with a `MockStorage`.
- Add `GET /api/health`, `GET /api/session/current`, `POST /api/session/new` assertions.

#### [NEW] `tests/test_storage_unit.py`
- Unit test `AlertStorage` in-memory fallback path (no Redis/Cassandra).
- Test: `store_alerts`, `get_alerts`, `get_stats`, `get_timeline`, `delete_session`, `delete_all_sessions`.
- No external dependencies — always runs in CI.

#### [MODIFY] `pytest.ini`
- Add `addopts = --tb=short -q` for cleaner CI output.
- Add `testpaths = tests` to make invocation unambiguous.

---

## 2. Jenkinsfile

### What's good
- Declarative pipeline ✅
- `STUB_MODELS=true` env var ✅  
- JUnit XML report ✅
- Branch-gated deploy ✅
- Cleanup stage ✅

### Gaps (for a DevOps portfolio)

| Gap | Fix |
|---|---|
| No **coverage report** | Add `--cov=. --cov-report=xml` to pytest, publish with `cobertura` plugin |
| No **integration test stage** | Add Stage 4b: spin up `docker-compose.ci.yml`, run with `NIDS_RUN_INTEGRATION=1`, tear down |
| No **Docker push** | Add stage after Build: push image to DockerHub/GHCR with credentials |
| `sleep 20` for healthcheck is fragile | Replace with `docker compose --wait` (compose v2) or a `wait-for-healthy.sh` loop |
| No **parallel stages** | Lint + Unit Test can run in parallel (`parallel {}` block) |
| No **environment cleanup** on failure | `post { always { sh 'docker compose -f docker-compose.ci.yml down --remove-orphans' } }` |
| `cleanup` stage uses `rm -rf venv` — fails on Windows agents | Use `sh` only, acceptable for Linux CI |
| No **artifact archiving** | Archive `test-results.xml`, `coverage.xml` |

### Proposed new stage order
```
1. Checkout
2. Install Dependencies  
3. Parallel: [ Lint | Unit Tests + Coverage ]
4. Integration Tests  (docker-compose.ci.yml up → pytest -m integration → down)
5. Build Docker Image
6. Push Docker Image   (credentials-bound, any branch → push; master → tag :latest)
7. Deploy             (master only)
```

---

## Proposed Changes

### Component: Tests

#### [MODIFY] tests/test_dashboard_api.py
Replace config-only tests with real Flask test client tests via `create_app()`.

#### [NEW] tests/test_storage_unit.py
In-memory `AlertStorage` unit tests. Zero external deps.

#### [MODIFY] pytest.ini
Add `addopts` and `testpaths`.

---

### Component: CI/CD

#### [MODIFY] Jenkinsfile
- Add parallel block for Lint + Unit Tests
- Add integration test stage (with compose up/down)
- Add coverage publishing
- Add Docker push stage with `withCredentials`
- Fix deploy healthcheck (replace `sleep 20`)
- Add `post { always { ... } }` for CI compose teardown
- Archive XML artifacts

---

## Suggestions (Optional but impactful for portfolio)

1. **Add a `Makefile`** — `make test`, `make lint`, `make run` makes the project look pro and simplifies Jenkinsfile steps.
2. **GitHub Actions fallback** — Add `.github/workflows/ci.yml` as a secondary CI demonstration (some reviewers prefer GitHub Actions over Jenkins).
3. **Add `healthcheck` to `docker-compose.yml` app service** — shows awareness of container readiness.
4. **`DATASTORE_QUERIES.md`** is untracked — commit it. It demonstrates schema design decisions.
5. **Commit `pytest.ini`** — currently untracked, needs to be in repo for Jenkins to pick it up.

---

## Verification Plan

1. `pytest tests/ -v` — all unit tests pass, integration tests skipped
2. Jenkinsfile syntax: `java -jar jenkins-cli.jar declarative-linter < Jenkinsfile`
3. Docker build: `docker build -t nids-app:test .`
4. CI compose: `docker compose -f docker-compose.ci.yml up -d && NIDS_RUN_INTEGRATION=1 pytest tests/ -m integration`
