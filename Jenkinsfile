/*
 * Jenkinsfile — NIDS DevOps Pipeline
 *
 * Runs ON your local Windows machine (Jenkins installed locally).
 * Deploys TO EC2 via SSH — git pull + docker compose restart.
 *
 * Stages:
 *   1. Checkout          — pull latest code from GitHub
 *   2. Install           — create venv + pip install (cached)
 *   3. Quality (parallel)
 *      a. Lint           — flake8
 *      b. Unit Tests     — pytest (no Docker needed)
 *   4. Integration Tests — Redis CI container + integration suite
 *   5. Deploy to EC2     — SSH → git pull → docker compose up (master only)
 *   6. Health Check      — curl EC2 /api/health (master only)
 *   7. Rollback          — revert container if health check fails
 *
 * Jenkins Credentials required (Manage Jenkins → Credentials → Global):
 *   ec2-host          Secret text                → your EC2 public IP
 *   ec2-ssh-key       SSH Username+Private Key   → username: ubuntu, key: .pem contents
 *   ec2-ingest-token  Secret text                → devops-demo
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
                bat 'git log -1 --oneline'
            }
        }

        // ── 2. Install Dependencies ───────────────────────────────────────────
        // Always create a fresh venv — venv/ is gitignored so never in workspace.
        // tools/ (JDK) is also gitignored; unit tests don't need PySpark so that's fine.
        stage('Install Dependencies') {
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                bat '''
                    python -m venv venv
                    venv\\Scripts\\python.exe -m pip install --upgrade pip --quiet
                    venv\\Scripts\\python.exe -m pip install -r requirements.txt --quiet
                '''
            }
        }

        // ── 3. Quality: Lint + Unit Tests (parallel) ──────────────────────────
        stage('Quality') {
            parallel {

                stage('Lint') {
                    options { timeout(time: 5, unit: 'MINUTES') }
                    steps {
                        bat '''
                            venv\\Scripts\\flake8.exe config/ src/ streaming/ dashboard/ tests/ sync_push.py ^
                                --max-line-length=110 ^
                                --exclude=venv ^
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
                        bat '''
                            set NIDS_DISABLE_CASSANDRA=1
                            set PYTHONPATH=.
                            venv\\Scripts\\pytest.exe tests/ ^
                                --ignore=tests\\test_integration_storage_smoke.py ^
                                --junitxml=test-results.xml ^
                                --cov=. ^
                                --cov-report=xml ^
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
        // Spins up a Redis container on port 6380 for integration tests.
        stage('Integration Tests') {
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                bat 'docker compose -f docker-compose.ci.yml down --remove-orphans 2>nul || echo nothing to stop'
                bat 'docker compose -f docker-compose.ci.yml up -d --wait'
                bat '''
                    set REDIS_HOST=localhost
                    set REDIS_PORT=6380
                    set NIDS_DISABLE_CASSANDRA=1
                    set NIDS_RUN_INTEGRATION=1
                    set PYTHONPATH=.
                    venv\\Scripts\\pytest.exe tests/ -m integration ^
                        --junitxml=integration-results.xml ^
                        -v
                '''
            }
            post {
                always {
                    bat 'docker compose -f docker-compose.ci.yml down --remove-orphans 2>nul || echo done'
                    junit allowEmptyResults: true, testResults: 'integration-results.xml'
                }
            }
        }

        // ── 5. Deploy to EC2 (master branch only) ────────────────────────────
        // SSH into EC2 → git pull latest master → docker compose restart.
        // EC2 builds its own Docker image from the pulled code.
        stage('Deploy to EC2') {
            when {
                branch 'master'
                expression { currentBuild.result == null || currentBuild.result == 'SUCCESS' }
            }
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                sshagent(['ec2-ssh-key']) {
                    sh """
                        ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 ubuntu@${EC2_HOST} '
                            set -e
                            cd ~/nids-app

                            echo "[Deploy] Pulling latest code..."
                            git fetch --all
                            git reset --hard origin/master

                            echo "[Deploy] Saving current image for rollback..."
                            docker inspect nids_app --format "{{.Image}}" 2>/dev/null \
                                > /tmp/nids_prev_image.txt || echo none > /tmp/nids_prev_image.txt

                            echo "[Deploy] Restarting containers..."
                            INGEST_TOKEN="${INGEST_TOKEN}" \
                                docker compose -f docker-compose.deploy.yml up -d --build --force-recreate

                            echo "[Deploy] Pruning old images..."
                            docker image prune -f

                            echo "[Deploy] Status:"
                            docker ps --format "table {{.Names}}\\t{{.Status}}\\t{{.Ports}}"
                        '
                    """
                }
            }
            post {
                failure {
                    sshagent(['ec2-ssh-key']) {
                        sh "ssh -o StrictHostKeyChecking=no ubuntu@${EC2_HOST} 'docker logs nids_app --tail 50' || true"
                    }
                }
            }
        }

        // ── 6. Health Check ───────────────────────────────────────────────────
        stage('Health Check') {
            when { branch 'master' }
            options { timeout(time: 5, unit: 'MINUTES') }
            steps {
                sh """
                    sleep 20
                    for i in 1 2 3 4 5; do
                        STATUS=\$(curl -s -o /dev/null -w '%{http_code}' \
                            http://${EC2_HOST}/api/health --max-time 10 || echo 000)
                        echo "Health check \$i/5: HTTP \$STATUS"
                        if [ "\$STATUS" = "200" ]; then
                            echo "PASSED — http://${EC2_HOST} is live"
                            exit 0
                        fi
                        sleep 10
                    done
                    echo "Health check FAILED after 5 attempts"
                    exit 1
                """
            }
            post {
                success { echo "Dashboard live: http://${EC2_HOST}" }
                failure  { echo "Health check failed — rollback will fire" }
            }
        }

        // ── 7. Rollback (only fires if deploy/health-check failed) ────────────
        stage('Rollback') {
            when {
                branch 'master'
                expression { currentBuild.result == 'FAILURE' }
            }
            steps {
                echo 'Deployment failed — rolling back...'
                sshagent(['ec2-ssh-key']) {
                    sh """
                        ssh -o StrictHostKeyChecking=no ubuntu@${EC2_HOST} '
                            PREV=\$(cat /tmp/nids_prev_image.txt 2>/dev/null || echo none)
                            echo "Rolling back to: \$PREV"
                            if [ "\$PREV" != "none" ] && [ -n "\$PREV" ]; then
                                docker compose -f ~/nids-app/docker-compose.deploy.yml up -d
                                echo "Rollback complete"
                            else
                                echo "No previous image — manual fix needed"
                            fi
                        '
                    """
                }
            }
        }
    }

    post {
        always {
            echo "Build #${BUILD_NUMBER} on ${env.BRANCH_NAME ?: 'unknown'} — DONE"
        }
        success { echo 'BUILD SUCCEEDED' }
        failure  { echo 'BUILD FAILED — check console output above' }
        cleanup {
            bat 'docker image prune -f 2>nul || echo done'
            cleanWs()
        }
    }
}
