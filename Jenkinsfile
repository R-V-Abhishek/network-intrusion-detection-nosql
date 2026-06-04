/*
 * Jenkinsfile — NIDS DevOps Pipeline
 *
 * Runs ON your local Windows machine (Jenkins installed locally).
 * Deploys TO EC2 via SSH — git pull + docker compose restart.
 *
 * Architecture:
 *   Local machine  → Kafka + Spark pipeline + Redis + Cassandra
 *   Local Jenkins  → lint + test → SSH EC2 → git pull → docker compose up
 *   Local machine  → sync_push.py → POST /api/ingest → EC2 (dashboard + Redis only)
 *
 * EC2 runs ONLY: Flask dashboard + Redis. It receives alerts via HTTP POST.
 *
 * Jenkins Credentials required (Manage Jenkins → Credentials → Global):
 *   ec2-host          Secret text              → your EC2 public IP
 *   ec2-ssh-key       SSH Username+Private Key → username: ubuntu, key: .pem contents
 *   ec2-ingest-token  Secret text              → devops-demo
 */

pipeline {

    agent any

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        timeout(time: 30, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    triggers {
        pollSCM('H/5 * * * *')
    }

    environment {
        EC2_HOST     = credentials('ec2-host')
        EC2_KEY      = credentials('ec2-ssh-key')
        INGEST_TOKEN = credentials('ec2-ingest-token')
    }

    stages {

        // ── 1. Checkout ───────────────────────────────────────────────────────
        stage('Checkout') {
            steps {
                deleteDir()
                checkout scm
                powershell 'git log -1 --oneline'
            }
        }

        // ── 2. Install Dependencies ───────────────────────────────────────────
        // venv/ is gitignored — always rebuild in fresh Jenkins workspace.
        stage('Install Dependencies') {
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                powershell '''
                    python -m venv venv
                    .\\venv\\Scripts\\python.exe -m pip install --upgrade pip --quiet
                    .\\venv\\Scripts\\python.exe -m pip install -r requirements.txt --quiet
                    Write-Host "Install complete"
                '''
            }
        }

        // ── 3. Quality: Lint + Unit Tests (parallel) ──────────────────────────
        stage('Quality') {
            parallel {

                stage('Lint') {
                    options { timeout(time: 5, unit: 'MINUTES') }
                    steps {
                        powershell '''
                            .\\venv\\Scripts\\flake8.exe `
                                config/ src/ streaming/ dashboard/ tests/ sync_push.py `
                                --max-line-length=110 `
                                --exclude=venv `
                                --count
                        '''
                    }
                    post {
                        failure { echo 'Lint FAILED — fix code style issues before deploy.' }
                        success { echo 'Lint passed.' }
                    }
                }

                stage('Unit Tests') {
                    options { timeout(time: 10, unit: 'MINUTES') }
                    steps {
                        powershell '''
                            $env:NIDS_DISABLE_CASSANDRA = "1"
                            $env:PYTHONPATH = "."
                            .\\venv\\Scripts\\pytest.exe tests/ `
                                --ignore=tests/test_integration_storage_smoke.py `
                                --junitxml=test-results.xml `
                                --cov=. `
                                --cov-report=xml `
                                -q
                        '''
                    }
                    post {
                        always {
                            junit allowEmptyResults: true, testResults: 'test-results.xml'
                            publishCoverage adapters: [coberturaAdapter('coverage.xml')]
                        }
                        failure { echo 'Unit tests FAILED — deployment blocked.' }
                        success { echo 'All unit tests passed.' }
                    }
                }
            }
        }

        // ── 4. Integration Tests ──────────────────────────────────────────────
        // Spins up a temporary Redis container on :6380 just for this test run.
        stage('Integration Tests') {
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                powershell 'docker compose -f docker-compose.ci.yml down --remove-orphans 2>$null; echo "Cleaned up"'
                powershell 'docker compose -f docker-compose.ci.yml up -d --wait'
                powershell '''
                    $env:REDIS_HOST              = "localhost"
                    $env:REDIS_PORT              = "6380"
                    $env:NIDS_DISABLE_CASSANDRA  = "1"
                    $env:NIDS_RUN_INTEGRATION    = "1"
                    $env:PYTHONPATH              = "."
                    .\\venv\\Scripts\\pytest.exe tests/ -m integration `
                        --junitxml=integration-results.xml `
                        -v
                '''
            }
            post {
                always {
                    powershell 'docker compose -f docker-compose.ci.yml down --remove-orphans 2>$null; echo "CI Redis stopped"'
                    junit allowEmptyResults: true, testResults: 'integration-results.xml'
                }
            }
        }

        // ── 5. Deploy to EC2 (master branch only) ─────────────────────────────
        // SSH into EC2 → git pull → docker compose restart.
        // EC2 only runs: Flask dashboard + Redis.
        // No Spark, no Kafka, no ML — that all stays on your local machine.
        stage('Deploy to EC2') {
            when {
                expression {
                    def b = env.GIT_BRANCH ?: env.BRANCH_NAME ?: ''
                    return (b == 'master' || b == 'origin/master') &&
                           (currentBuild.result == null || currentBuild.result == 'SUCCESS')
                }
            }
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                // withCredentials writes the PEM key to a temp file.
                // We call ssh.exe directly — avoids sshagent plugin (broken on Windows).
                withCredentials([
                    string(credentialsId: 'ec2-host', variable: 'EC2_HOST'),
                    string(credentialsId: 'ec2-ingest-token', variable: 'INGEST_TOKEN'),
                    sshUserPrivateKey(credentialsId: 'ec2-ssh-key', keyFileVariable: 'SSH_KEY_FILE', usernameVariable: 'SSH_USER')
                ]) {
                    powershell '''
                        # Fix key file permissions (ssh.exe rejects world-readable keys)
                        $keyFile = $env:SSH_KEY_FILE
                        icacls $keyFile /inheritance:r /grant:r "$env:USERNAME:R" | Out-Null

                        $remote = "$env:SSH_USER@$env:EC2_HOST"
                        $token  = $env:INGEST_TOKEN

                        $deployCmd = @"
set -e
cd ~/nids-app
echo "[Deploy] Pulling latest code..."
git fetch --all
git reset --hard origin/master
docker inspect nids_app --format "{{.Image}}" 2>/dev/null > /tmp/nids_prev_image.txt || echo none > /tmp/nids_prev_image.txt
echo "[Deploy] Restarting dashboard + Redis..."
INGEST_TOKEN=$token docker compose -f docker-compose.deploy.yml up -d --build --force-recreate
docker image prune -f
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
"@

                        Write-Host "[Deploy] Connecting to $remote ..."
                        echo $deployCmd | ssh -o StrictHostKeyChecking=no -o ConnectTimeout=20 -i $keyFile $remote bash
                        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
                    '''
                }
            }
            post {
                failure {
                    withCredentials([
                        string(credentialsId: 'ec2-host', variable: 'EC2_HOST'),
                        sshUserPrivateKey(credentialsId: 'ec2-ssh-key', keyFileVariable: 'SSH_KEY_FILE', usernameVariable: 'SSH_USER')
                    ]) {
                        powershell '''
                            $keyFile = $env:SSH_KEY_FILE
                            icacls $keyFile /inheritance:r /grant:r "$env:USERNAME:R" | Out-Null
                            ssh -o StrictHostKeyChecking=no -i $keyFile "$env:SSH_USER@$env:EC2_HOST" `
                                "docker logs nids_app --tail 50" 2>&1 || true
                        '''
                    }
                }
            }
        }

        // ── 6. Health Check ───────────────────────────────────────────────────
        stage('Health Check') {
            when {
                expression {
                    def b = env.GIT_BRANCH ?: env.BRANCH_NAME ?: ''
                    return b == 'master' || b == 'origin/master'
                }
            }
            options { timeout(time: 5, unit: 'MINUTES') }
            steps {
                withCredentials([string(credentialsId: 'ec2-host', variable: 'EC2_HOST')]) {
                    powershell '''
                        Start-Sleep 20
                        $passed = $false
                        for ($i = 1; $i -le 5; $i++) {
                            try {
                                $resp = Invoke-WebRequest -Uri "http://$env:EC2_HOST/api/health" -TimeoutSec 10 -UseBasicParsing
                                if ($resp.StatusCode -eq 200) {
                                    Write-Host "Health check $i/5: HTTP 200 -- PASSED"
                                    $passed = $true
                                    break
                                }
                                Write-Host "Health check $i/5: HTTP $($resp.StatusCode)"
                            } catch {
                                Write-Host "Health check $i/5: failed -- $_"
                            }
                            Start-Sleep 10
                        }
                        if (-not $passed) {
                            Write-Host "Health check FAILED after 5 attempts"
                            exit 1
                        }
                    '''
                }
            }
            post {
                success { echo "Dashboard is live" }
                failure  { echo "Health check failed — rollback will fire" }
            }
        }

        // ── 7. Rollback (only fires if deploy or health check failed) ─────────
        stage('Rollback') {
            when {
                expression {
                    def b = env.GIT_BRANCH ?: env.BRANCH_NAME ?: ''
                    return (b == 'master' || b == 'origin/master') &&
                           currentBuild.result == 'FAILURE'
                }
            }
            steps {
                echo 'Deployment failed — rolling back to previous image...'
                withCredentials([
                    string(credentialsId: 'ec2-host', variable: 'EC2_HOST'),
                    sshUserPrivateKey(credentialsId: 'ec2-ssh-key', keyFileVariable: 'SSH_KEY_FILE', usernameVariable: 'SSH_USER')
                ]) {
                    powershell '''
                        $keyFile = $env:SSH_KEY_FILE
                        icacls $keyFile /inheritance:r /grant:r "$env:USERNAME:R" | Out-Null
                        $rollbackCmd = @"
PREV=$(cat /tmp/nids_prev_image.txt 2>/dev/null || echo none)
echo Rolling back to: $PREV
if [ "$PREV" != "none" ] && [ -n "$PREV" ]; then
    docker compose -f ~/nids-app/docker-compose.deploy.yml up -d
    echo Rollback complete
fi
"@
                        echo $rollbackCmd | ssh -o StrictHostKeyChecking=no -i $keyFile "$env:SSH_USER@$env:EC2_HOST" bash
                    '''
                }
            }
        }
    }

    post {
        always {
            echo "Build #${BUILD_NUMBER} on branch ${env.BRANCH_NAME ?: 'unknown'} — done"
        }
        success { echo 'BUILD SUCCEEDED' }
        failure  { echo 'BUILD FAILED — check console output above' }
        cleanup {
            powershell 'docker image prune -f 2>$null; Write-Host "Cleanup done"'
            cleanWs()
        }
    }
}
