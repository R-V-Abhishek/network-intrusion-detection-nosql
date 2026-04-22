/*
 * Jenkinsfile — Declarative Pipeline for NIDS DevOps Demo
 *
 *  1. Checkout  — pull latest code
 *  2. Install   — pip install into venv
 *  3. Quality   — lint (flake8) + unit tests (pytest) in parallel
 *  4. Integration Tests — spin up CI compose stack, run integration suite
 *  5. Build     — docker build local image
 *  6. Deploy    — docker compose up full stack (master only)
 */

pipeline {

    agent any

    options {
        buildDiscarder(logRotator(numToKeepStr: '10', artifactNumToKeepStr: '3'))
    }

    environment {
        IMAGE_NAME = "nids-app"
        IMAGE_TAG  = "${BUILD_NUMBER}"

        STUB_MODELS = "true"
        REDIS_HOST  = "redis"
        REDIS_PORT  = "6379"
    }

    stages {

        stage('Checkout') {
            steps {
                checkout scm
                echo "Code checked out"
            }
        }

        stage('Install Dependencies') {
            steps {
                sh '''
                    python3 -m venv venv
                    venv/bin/pip install --upgrade pip
                    venv/bin/pip install -r requirements.txt
                '''
            }
        }

        stage('Quality') {
            parallel {
                stage('Lint') {
                    steps {
                        sh '''
                            venv/bin/flake8 config/ src/ streaming/ dashboard/ tests/ \
                                --max-line-length=110 \
                                --exclude=venv \
                                --count
                        '''
                    }
                    post {
                        failure { echo "Lint issues found." }
                    }
                }

                stage('Unit Tests + Coverage') {
                    steps {
                        sh '''
                            venv/bin/pytest tests/ \
                                --junitxml=test-results.xml \
                                --cov=. \
                                --cov-report=xml
                        '''
                    }
                    post {
                        always {
                            junit 'test-results.xml'
                            publishCoverage adapters: [coberturaAdapter('coverage.xml')]
                            archiveArtifacts artifacts: 'test-results.xml,coverage.xml', fingerprint: true
                        }
                        failure { echo "Tests FAILED — will NOT deploy." }
                        success { echo "All unit tests passed!" }
                    }
                }
            }
        }

        stage('Integration Tests') {
            steps {
                sh '''
                    docker compose -f docker-compose.ci.yml down --remove-orphans || true
                    docker rm -f nids_redis_ci || true
                    docker compose -p nids_ci_${BUILD_NUMBER} -f docker-compose.ci.yml up -d --build --wait
                    docker compose -p nids_ci_${BUILD_NUMBER} -f docker-compose.ci.yml ps

                    REDIS_TEST_HOST=$(venv/bin/python - <<'PY'
import socket, subprocess, sys, time

port = 6379
candidates = ["localhost", "127.0.0.1", "host.docker.internal", "redis-ci", "redis"]

try:
    gw = subprocess.check_output("ip route | awk '/default/ {print $3; exit}'", shell=True, text=True).strip()
    if gw:
        candidates.append(gw)
except Exception:
    pass

seen = []
for h in candidates:
    if h and h not in seen:
        seen.append(h)

deadline = time.time() + 60
while time.time() < deadline:
    for h in seen:
        try:
            with socket.create_connection((h, port), timeout=2) as s:
                s.sendall(b"*1\\r\\n$4\\r\\nPING\\r\\n")
                if s.recv(16).startswith(b"+PONG"):
                    print(h); sys.exit(0)
        except OSError:
            continue
    time.sleep(2)
sys.exit(1)
PY
                    ) || {
                        echo "Redis on port 6379 not reachable"
                        docker compose -p nids_ci_${BUILD_NUMBER} -f docker-compose.ci.yml logs --tail=80 redis-ci || true
                        exit 1
                    }

                    REDIS_HOST=${REDIS_TEST_HOST} REDIS_PORT=6379 NIDS_DISABLE_CASSANDRA=1 NIDS_RUN_INTEGRATION=1 \
                        venv/bin/pytest tests/ -m integration --junitxml=integration-results.xml
                '''
            }
            post {
                always {
                    sh 'docker compose -p nids_ci_${BUILD_NUMBER} -f docker-compose.ci.yml down --remove-orphans || true'
                    junit allowEmptyResults: true, testResults: 'integration-results.xml'
                    archiveArtifacts artifacts: 'integration-results.xml', fingerprint: true
                }
            }
        }

        stage('Build Docker Image') {
            steps {
                sh '''
                    docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .
                    docker tag  ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:latest
                    echo "Built ${IMAGE_NAME}:${IMAGE_TAG} (local only)"
                '''
            }
        }

        stage('Deploy') {
            when {
                expression { env.GIT_BRANCH == 'origin/master' }
            }
            steps {
                sh '''
                    docker compose -f docker-compose.yml up -d --build --wait
                    docker compose -f docker-compose.yml ps
                '''
            }
            post {
                success { echo "Deployment successful! Dashboard: http://localhost:5000" }
                failure { sh 'docker compose -f docker-compose.yml logs --tail=50' }
            }
        }
    }

    post {
        always {
            echo "Pipeline finished. Build #${BUILD_NUMBER} on branch ${env.BRANCH_NAME}"
        }
        failure { echo "BUILD FAILED" }
        success { echo "BUILD SUCCEEDED" }
        cleanup {
            sh 'rm -rf venv'
            sh '''
                docker image ls --format '{{.Repository}}:{{.Tag}} {{.ID}}' \
                    | grep '^nids-app:' \
                    | awk '{print $2}' \
                    | sort -u \
                    | xargs -r docker image rm -f || true
                docker image prune -f || true
            '''
        }
    }
}
