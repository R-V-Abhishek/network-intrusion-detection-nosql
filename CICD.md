# CI/CD Setup Guide — NIDS Project

This document explains what was added, why, and how to set up Jenkins from scratch.  
Written for complete beginners — no prior DevOps knowledge assumed.

---

## What is CI/CD? (Plain English)

**CI = Continuous Integration**  
Every time someone pushes code, an automated system immediately:
1. Pulls the new code
2. Installs dependencies
3. Runs all tests
4. Tells you if something is broken — *before* it gets merged

**CD = Continuous Deployment**  
If all tests pass on the `master` branch, the system automatically deploys the application.

```
Developer pushes code to GitHub
           ↓
     Jenkins detects push
           ↓
    ┌──────────────────┐
    │  Install deps    │
    │  Run lint        │
    │  Run pytest      │  ← If any step fails, pipeline stops here (red build)
    │  Build Docker    │
    │  Deploy (master) │  ← Only runs if branch is master
    └──────────────────┘
           ↓
   Slack/Email: "Build #42 PASSED ✓"
```

---

## Files Added to This Repo

| File | Purpose |
|---|---|
| `Jenkinsfile` | Defines the entire pipeline — Jenkins reads this automatically |
| `tests/test_config.py` | Tests that config values are correct (39 features, valid attack types, etc.) |
| `tests/test_dashboard_api.py` | Tests alert severity logic and JSON serialisation |
| `tests/test_pipeline.py` | Tests STUB_MODELS flag and attack row filter logic |
| `docker-compose.ci.yml` | Lightweight Cassandra + Redis for running integration tests in Jenkins |

None of the tests require Spark, Kafka, or trained models. They test pure logic so they pass even while the project is still being built.

---

## How the Jenkinsfile Works

```
pipeline {
    stages {
        Stage 1: Checkout    → Jenkins pulls your code from GitHub
        Stage 2: Install     → pip install -r requirements.txt (inside a venv)
        Stage 3: Lint        → flake8 checks for Python syntax/style errors
        Stage 4: Test        → pytest tests/ runs all test files
        Stage 5: Build       → docker build creates the app image
        Stage 6: Deploy      → docker compose up (ONLY on master branch)
    }
}
```

**Key behaviour:**
- If `pytest` fails → pipeline stops at Stage 4, Docker image is never built, nothing deploys
- If the branch is `feature/anything` → Stages 1–5 run, Stage 6 (Deploy) is skipped
- If the branch is `master` → all 6 stages run

---

## Setting Up Jenkins (Step by Step)

### Step 1 — Install Jenkins

**Option A: Docker (recommended, no install needed)**
```bash
docker run -d \
  -p 8080:8080 \
  -p 50000:50000 \
  -v jenkins_home:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --name jenkins \
  jenkins/jenkins:lts
```

Then open: `http://localhost:8080`

Get the initial admin password:
```bash
docker exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

**Option B: Direct install (Windows)**  
Download from https://www.jenkins.io/download/ → run the `.msi` installer → opens at `http://localhost:8080`

---

### Step 2 — First-Time Jenkins Setup

1. Paste the admin password from Step 1
2. Click **"Install suggested plugins"** — wait ~3 minutes
3. Create your admin user (remember the password)
4. Leave the URL as `http://localhost:8080` → click **Save and Finish**

---

### Step 3 — Install Required Plugins

Go to: **Manage Jenkins → Plugins → Available plugins**

Search for and install these:
- `Git` (usually pre-installed)
- `Pipeline` (usually pre-installed)
- `GitHub Integration` ← needed for webhooks
- `JUnit` ← shows test results in Jenkins UI

Click **Install without restart** → tick **Restart Jenkins when installation is complete**

---

### Step 4 — Create the Pipeline Job

1. Jenkins home → **New Item**
2. Name it: `nids-pipeline`
3. Select **Pipeline** → click **OK**
4. Scroll to the **Pipeline** section at the bottom
5. Change **Definition** to: `Pipeline script from SCM`
6. **SCM** → `Git`
7. **Repository URL** → paste your GitHub repo URL  
   e.g. `https://github.com/your-username/network-intrusion-detection-nosql.git`
8. **Branch Specifier** → `*/master`
9. **Script Path** → `Jenkinsfile`  (this is the file Jenkins will read)
10. Click **Save**

---

### Step 5 — Connect GitHub to Jenkins (Webhooks)

This makes Jenkins trigger automatically on every push.

**In GitHub:**
1. Your repo → **Settings → Webhooks → Add webhook**
2. **Payload URL**: `http://<your-ip>:8080/github-webhook/`
   - If Jenkins is on your local machine, use your machine's IP (not `localhost`)
   - If your machine is behind a router, use a tunnelling tool like `ngrok`:  
     ```bash
     ngrok http 8080
     # Copy the https URL it gives you
     ```
3. **Content type**: `application/json`
4. **Which events**: `Just the push event`
5. Click **Add webhook**

**In Jenkins:**
1. Go to `nids-pipeline` → **Configure**
2. Under **Build Triggers** → tick **GitHub hook trigger for GITScm polling**
3. Save

Now every `git push` will trigger a Jenkins build automatically.

---

### Step 6 — Run Your First Build

1. Jenkins → `nids-pipeline` → **Build Now**
2. Click the build number (e.g. `#1`) → **Console Output**
3. Watch it run through all stages

A passing build looks like:
```
[Pipeline] stage: Checkout      ✓
[Pipeline] stage: Install        ✓
[Pipeline] stage: Lint           ✓
[Pipeline] stage: Test           ✓  (e.g. 25 passed)
[Pipeline] stage: Build          ✓
[Pipeline] stage: Deploy         ✓  (master only)
Finished: SUCCESS
```

---

## Running Tests Locally (Before Pushing)

Always run tests locally first to catch failures before Jenkins does:

```powershell
# Activate venv (Windows)
.\venv\Scripts\Activate.ps1

# Install deps (first time only)
pip install -r requirements.txt

# Run all tests
pytest tests/ -v

# Run just one test file
pytest tests/test_config.py -v

# Run with short traceback on failure
pytest tests/ --tb=short
```

---

## What Each Test File Checks

### `tests/test_config.py`
- UNSW feature list has exactly 39 features with no duplicates
- Attack type mapping has exactly 10 classes, Normal=0
- All model paths are defined as strings
- Alert severity covers every attack type
- Confidence threshold is between 0 and 1

### `tests/test_dashboard_api.py`
- High severity attacks (DoS, Exploits, Backdoors) are correctly labelled
- Normal traffic maps to "info" severity
- Attack type mapping can be serialised to JSON (required for `/api/attack-types`)

### `tests/test_pipeline.py`
- `STUB_MODELS=true` env var is parsed correctly (case-insensitive)
- Attack row filter returns only rows where `binary_prediction == 1`
- High-confidence filter uses `ALERT_CONFIG` threshold correctly

---

## Adding New Tests

When you finish a module, add tests for it in `tests/`. Follow this pattern:

```python
# tests/test_my_module.py

def test_my_function_returns_correct_type():
    from my_module import my_function
    result = my_function(some_input)
    assert isinstance(result, expected_type)

def test_edge_case():
    from my_module import my_function
    result = my_function(edge_case_input)
    assert result == expected_output
```

Rule: **tests must not need Kafka, Spark, or Cassandra running**. Test pure logic only. Use mocks for external services.

---

## Branch Strategy with Jenkins

```
master          → Jenkins runs all 6 stages including Deploy
                  Only receives code via merged PRs (never push directly)

feature/p1-*   → Jenkins runs stages 1–5 (no Deploy)
feature/p2-*   → Jenkins runs stages 1–5 (no Deploy)
feature/p3-*   → Jenkins runs stages 1–5 (no Deploy)
```

**Workflow for each person:**
```bash
# Work on your feature branch
git checkout feature/p1-ingestion-binary
# ... make changes ...
git add .
git commit -m "Add preprocessing utilities"
git push origin feature/p1-ingestion-binary

# Jenkins automatically runs tests on your branch
# If green → open PR on GitHub → project head reviews → merges to master
# If red   → fix the failing tests → push again
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Jenkins can't find `python3` | Install Python on the Jenkins machine; or use `python` instead of `python3` in Jenkinsfile |
| Jenkins can't run `docker` | Run Jenkins with `-v /var/run/docker.sock:/var/run/docker.sock` (see Step 1) |
| Webhook not triggering | Use `ngrok` to expose localhost; check GitHub webhook delivery logs |
| Tests fail only in Jenkins | Check if `STUB_MODELS=true` is set in the `environment` block of Jenkinsfile |
| `flake8` fails on line length | Max line length is set to 110 in Jenkinsfile — keep lines under that |
