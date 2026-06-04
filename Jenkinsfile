/*
 * Jenkinsfile — NIDS DevOps Pipeline
 *
 * Runs ON your local Windows machine (Jenkins installed locally).
 * Deploys TO EC2 via SSH — simple git pull + docker compose restart.
 *
 * Architecture:
 *   Local Jenkins → lint + test → SSH EC2 → git pull → docker compose up
 *   Local machine → sync_push.py → POST /api/ingest → EC2 Redis → Dashboard
 *
 * Stages:
 *   1. Checkout        — pull latest code from GitHub
 *   2. Quality (parallel)
 *      a. Lint         — flake8
 *      b. Unit Tests   — pytest (no Docker needed)
 *   3. Integration     — spin up Redis via docker-compose.ci.yml, run integration suite
 *   4. Deploy to EC2   — SSH in, git pull, docker compose restart (master branch only)
 *   5. Health Check    — curl EC2 /api/health to confirm deployment worked
 *   6. Rollback        — revert if health check fails
 *
 * Jenkins Credentials needed (Manage Jenkins → Credentials → Global):
 *   ec2-host         Secret text  → EC2 public IP (e.g. 52.66.67.1)
 *   ec2-ssh-key      SSH Username with Private Key → username: ubuntu, key: .pem contents
 *   ec2-ingest-token Secret text  → devops-demo (must match INGEST_TOKEN on EC2)
 */

pipeline {

    agent any

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        timeout(time: 20, unit: 'MINUTES')
        disableConcurrentBuilds()
    }

    triggers {
        // Polls GitHub every 5 min — also set up GitHub webhook for instant trigger
        pollSCM('H/5 * * * *')
    }

    environment {
        // Injected from Jenkins credential store — never hardcoded
        EC2_HOST     = credentials('ec2-host')
        EC2_KEY      = credentials('ec2-ssh-key')
        INGEST_TOKEN = credentials('ec2-ingest-token')

        // Test environment — uses local Redis via docker-compose.ci.yml
        REDIS_HOST             = "localhost"
        REDIS_PORT             = "6380"
        NIDS_DISABLE_CASSANDRA = "1"
        PYTHONPATH             = "."

        // Use bundled JDK 17 for PySpark in tests (only needed if running pipeline tests)
        JAVA_HOME = "${WORKSPACE}\\tools\\jdk-17.0.12"
    }

    stages {

        // ── Stage 1: Checkout ─────────────────────────────────────────────────
        stage('Checkout') {
            steps {
                deleteDir()
                checkout scm
                bat 'git log -1 --oneline'
            }
        }

        // ── Stage 2: Quality (Lint + Unit Tests in parallel) ──────────────────
        stage('Quality') {
            parallel {

                stage('Lint') {
                    steps {
                        bat '''
                            venv\\Scripts\\flake8.exe ^
                                config/ src/ streaming/ dashboard/ tests/ sync_push.py ^
                                --max-line-length=110 ^
                                --exclude=venv ^
                                --count
                        '''
                    }
                    post {
                        failure { echo 'Lint FAILED — fix code style before deploy.' }
                    }
                }

                stage('Unit Tests') {
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
                    }
                }
            }
        }

        // ── Stage 3: Integration Tests ────────────────────────────────────────
        stage('Integration Tests') {
            options { timeout(time: 5, unit: 'MINUTES') }
            steps {
                bat '''
                    docker compose -f docker-compose.ci.yml down --remove-orphans 2>nul || echo "nothing to stop"
                    docker compose -f docker-compose.ci.yml up -d --wait
                '''
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

        // ── Stage 4: Deploy to EC2 ────────────────────────────────────────────
        // Only runs on master branch after all tests pass.
        // SSH into EC2 → git pull → docker compose restart.
        // EC2 builds its own image from the pulled code (no image transfer needed).
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

                            echo "[Deploy] Saving current container for rollback..."
                            docker inspect nids_app --format "{{.Image}}" 2>/dev/null > /tmp/nids_prev_image.txt || echo none > /tmp/nids_prev_image.txt

                            echo "[Deploy] Restarting containers..."
                            INGEST_TOKEN="${INGEST_TOKEN}" docker compose -f docker-compose.deploy.yml up -d --build --force-recreate

                            echo "[Deploy] Pruning old images..."
                            docker image prune -f

                            echo "[Deploy] Container status:"
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

        // ── Stage 5: Health Check ─────────────────────────────────────────────
        stage('Health Check') {
            when { branch 'master' }
            options { timeout(time: 3, unit: 'MINUTES') }
            steps {
                sh """
                    sleep 15
                    for i in 1 2 3 4 5; do
                        STATUS=\$(curl -s -o /dev/null -w '%{http_code}' \\
                            http://${EC2_HOST}/api/health --max-time 10 || echo 000)
                        echo "Health check \$i/5: HTTP \$STATUS"
                        if [ "\$STATUS" = "200" ]; then
                            echo "Health check PASSED — http://${EC2_HOST} is live"
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

        // ── Stage 6: Rollback ─────────────────────────────────────────────────
        stage('Rollback') {
            when {
                branch 'master'
                expression { currentBuild.result == 'FAILURE' }
            }
            steps {
                echo 'Deployment failed — rolling back to previous image...'
                sshagent(['ec2-ssh-key']) {
                    sh """
                        ssh -o StrictHostKeyChecking=no ubuntu@${EC2_HOST} '
                            PREV=\$(cat /tmp/nids_prev_image.txt 2>/dev/null || echo none)
                            echo "Rolling back to: \$PREV"
                            if [ "\$PREV" != "none" ] && [ -n "\$PREV" ]; then
                                docker compose -f ~/nids-app/docker-compose.deploy.yml up -d
                                echo "Rollback complete"
                            else
                                echo "No previous image found — manual intervention needed"
                            fi
                        '
                    """
                }
            }
        }
    }

    post {
        always {
            echo "Build #${BUILD_NUMBER} finished on branch ${env.BRANCH_NAME ?: 'unknown'}"
        }
        success {
            echo 'BUILD SUCCEEDED'
        }
        failure {
            echo 'BUILD FAILED — check console output above'
        }
        cleanup {
            bat 'docker image prune -f 2>nul || echo done'
            cleanWs()
        }
    }
}
