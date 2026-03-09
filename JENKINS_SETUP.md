# Jenkins CI/CD — Setup Log & Teammate Guide

**Author:** R V Abhishek  
**Date completed:** March 4, 2026  
**Branch:** This file lives on `master` and applies to all branches.

---

## What Was Achieved

The CI/CD pipeline written by the team was wired up end-to-end and verified with a **fully green build** (Build #8):

| Stage | Status | What it does |
|---|---|---|
| Checkout | ✅ | Pulls latest code from GitHub |
| Install Dependencies | ✅ | Creates venv, installs `requirements.txt` |
| Lint | ✅ 0 errors | `flake8` on `config/ src/ streaming/ dashboard/ tests/` |
| Test | ✅ 38/38 passed | `pytest tests/` with JUnit XML output |
| Build Docker Image | ✅ | Builds `nids-app:<build_number>` + tags as `latest` |
| Deploy | ✅ | `docker compose up -d` — runs on `master` only |

Every `git push` and pull request now **automatically triggers** this pipeline via GitHub webhook.

---

## Infrastructure Overview

```
GitHub repo
    │
    │  push / pull_request event
    ▼
GitHub Webhook
    │
    │  POST to https://unattackable-agueda-unauthoritatively.ngrok-free.dev/github-webhook/
    ▼
ngrok tunnel (running on Abhishek's machine)
    │
    │  forwards to localhost:8080
    ▼
Jenkins (Docker container, port 8080)
    │
    │  reads Jenkinsfile from repo
    ▼
Pipeline runs (Lint → Test → Build → Deploy)
```

---

## What Was Fixed vs. Original Jenkinsfile

The Jenkinsfile committed by the team had two issues that were fixed:

### Fix 1 — Deploy stage never ran
**Original:**
```groovy
when { branch 'main' }
```
**Fixed to:**
```groovy
when { expression { env.GIT_BRANCH == 'origin/master' } }
```
The repo's default branch is `master`, not `main`. The deploy stage was silently skipped on every build.

### Fix 2 — docker-compose port binding blocked by Windows firewall
**Original** (in `docker-compose.yml`):
```yaml
ports:
  - "6379:6379"   # redis
  - "9042:9042"   # cassandra
```
**Fixed to:**
```yaml
expose:
  - "6379"   # redis
expose:
  - "9042"   # cassandra
```
`expose` makes ports reachable between containers on the internal `nids_net` network without binding to the Windows host. The Cassandra port bind was blocked by Windows socket permissions and caused the Deploy stage to fail.

---

## How to Restart Everything After a Machine Reboot

All three components need to be restarted in order:

### Step 1 — Start Docker Desktop
Open **Docker Desktop** from the Start menu. Wait for the whale icon in the system tray to go solid (30–60 seconds).

### Step 2 — Start Jenkins
```powershell
docker start jenkins
docker exec -u root jenkins bash -c "chmod 666 /var/run/docker.sock"
```
> The second command re-grants Docker socket access. It resets on every container restart — this is a known limitation of running Docker-in-Docker on Windows.

### Step 3 — Start ngrok tunnel
```powershell
ngrok http --domain=unattackable-agueda-unauthoritatively.ngrok-free.dev 8080
```
> This uses a reserved static domain — the URL never changes, so the GitHub webhook never needs updating.

**Keep this terminal open** while working. If it closes, the webhook stops receiving events (Jenkins still works, it just won't auto-trigger from GitHub).

### Verify everything is working
```powershell
docker ps   # should show jenkins container running
```
Then open http://localhost:8080 — login and confirm Jenkins is up.

---

## How the Webhook Is Configured (GitHub side)

**Location:** GitHub repo → Settings → Webhooks

| Field | Value |
|---|---|
| Payload URL | `https://unattackable-agueda-unauthoritatively.ngrok-free.dev/github-webhook/` |
| Content type | `application/json` |
| Events | Pushes + Pull requests |
| Status | Active (green tick) |

Only the **repo owner (Abhishek)** can modify this — teammates do not need to touch it.

---

## How the Jenkins Job Is Configured

**Job name:** `nids-pipeline`  
**Job type:** Pipeline  
**Location:** http://localhost:8080/job/nids-pipeline/

Key settings:
- **Definition:** Pipeline script from SCM
- **SCM:** Git → `https://github.com/R-V-Abhishek/network-intrusion-detection-nosql.git`
- **Branch:** `*/master`
- **Script path:** `Jenkinsfile`
- **Build trigger:** GitHub hook trigger for GITScm polling ✅

---

## What Each Team Member Needs to Do

### Nothing extra — it just works.

When you push to your feature branch:
```bash
git push origin feature/your-branch
```
Jenkins automatically runs Stages 1–5 (no Deploy). You'll see the result at http://localhost:8080 on Abhishek's machine, or check GitHub webhook delivery logs.

When a PR is merged to `master`:
- Jenkins runs all 6 stages including Deploy
- The full stack (app + Redis + Cassandra) spins up via docker compose

### Before opening a PR — run tests locally first
```powershell
# Windows
.\venv\Scripts\Activate.ps1
pytest tests/ -v
flake8 config/ src/ streaming/ dashboard/ tests/ --max-line-length=110
```

```bash
# Linux/Mac
source venv/bin/activate
pytest tests/ -v
flake8 config/ src/ streaming/ dashboard/ tests/ --max-line-length=110
```

If both pass locally, Jenkins will pass too.

---

## Installed Software (Abhishek's machine)

| Software | Version | Purpose |
|---|---|---|
| Docker Desktop | 29.2.1 | Runs Jenkins and the app stack |
| Jenkins (Docker image) | `jenkins/jenkins:lts` | CI/CD server |
| Python 3 | 3.13.5 | Installed inside Jenkins container |
| Docker CLI | 26.1.5 | Installed inside Jenkins container for build stage |
| Docker Compose plugin | v2.24.6 | Installed inside Jenkins container for deploy stage |
| ngrok | 3.36.1 | Exposes Jenkins to GitHub webhooks |

---

## Jenkins Plugins Installed

- Git (pre-installed)
- Pipeline (pre-installed)
- **GitHub Integration Plugin** ← required for webhook trigger
- **JUnit** ← shows test pass/fail counts in Jenkins UI

---

## Branch Strategy (as documented in CICD.md)

```
master              → All 6 stages run, including Deploy
                      Never push directly — always merge via PR

feature/p1-*        → Stages 1–5 only (no Deploy)
feature/p2-*        → Stages 1–5 only (no Deploy)
feature/p3-*        → Stages 1–5 only (no Deploy)
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| Jenkins not opening at localhost:8080 | Container stopped | `docker start jenkins` |
| Docker build fails with "permission denied" | Socket permission reset after restart | `docker exec -u root jenkins bash -c "chmod 666 /var/run/docker.sock"` |
| Webhook not triggering Jenkins | ngrok tunnel closed | Restart ngrok with static domain command above |
| GitHub webhook shows red X | Wrong payload URL (missing trailing `/`) | URL must end with `/github-webhook/` |
| `pytest` fails only in Jenkins | Missing env var | Check `STUB_MODELS=true` is set in Jenkinsfile `environment` block |
| Deploy fails with port binding error | Windows firewall blocking host port | Already fixed — `docker-compose.yml` now uses `expose` not `ports` |
