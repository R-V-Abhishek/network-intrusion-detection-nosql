/*
 * Jenkinsfile — Declarative Pipeline for NIDS project
 *
 * WHAT THIS DOES (plain English):
 *  1. Checkout  — Jenkins pulls the latest code from GitHub
 *  2. Install   — pip install all dependencies into a venv
 *  3. Lint      — flake8 checks for obvious Python errors
 *  4. Test      — pytest runs all tests in tests/
 *  5. Build     — docker build creates the app image
 *  6. Deploy    — docker compose up starts the full stack
 *                 (only runs on the 'main' branch)
 *
 * HOW TO USE:
 *  - In Jenkins: New Item → Pipeline → "Pipeline script from SCM"
 *  - Point it at your GitHub repo
 *  - Jenkins will automatically find this Jenkinsfile
 */

pipeline {

    // Run on any available Jenkins agent (worker machine)
    agent any

    // Global environment variables available in every stage
    environment {
        // Name of the Docker image we'll build
        IMAGE_NAME = "nids-app"
        IMAGE_TAG  = "${BUILD_NUMBER}"   // each build gets a unique tag e.g. nids-app:42

        // Jenkins credentials id for Docker registry login
        DOCKER_CREDENTIALS_ID = "dockerhub-credentials"

        // Set this so tests don't try to connect to real Spark/Kafka/Cassandra
        STUB_MODELS = "true"
        REDIS_HOST = "redis"
        REDIS_PORT = "6379"
    }

    stages {

        // ── STAGE 1 ──────────────────────────────────────────────────────────
        stage('Checkout') {
            steps {
                // Jenkins does this automatically when using "Pipeline from SCM"
                // but keeping it explicit is good practice
                checkout scm
                echo "Code checked out"
            }
        }

        // ── STAGE 2 ──────────────────────────────────────────────────────────
        stage('Install Dependencies') {
            steps {
                sh '''
                    echo "=== Creating virtual environment ==="
                    python3 -m venv venv

                    echo "=== Installing dependencies ==="
                    venv/bin/pip install --upgrade pip
                    venv/bin/pip install -r requirements.txt
                '''
            }
        }

        // ── STAGE 3 ──────────────────────────────────────────────────────────
        stage('Quality') {
            parallel {
                stage('Lint') {
                    steps {
                        sh '''
                            echo "=== Running flake8 linter ==="
                            venv/bin/flake8 config/ src/ streaming/ dashboard/ tests/ \
                                --max-line-length=110 \
                                --exclude=venv \
                                --count
                        '''
                    }
                    post {
                        failure {
                            echo "Lint issues found — fix them before merging!"
                        }
                    }
                }

                stage('Unit Tests + Coverage') {
                    steps {
                        sh '''
                            echo "=== Running unit tests with coverage ==="
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
                        failure {
                            echo "Tests FAILED — this code will NOT be deployed."
                        }
                        success {
                            echo "All unit tests passed!"
                        }
                    }
                }
            }
        }

        // ── STAGE 4 ──────────────────────────────────────────────────────────
        stage('Integration Tests') {
            steps {
                sh '''
                    echo "=== Starting CI compose stack ==="
                    docker compose -f docker-compose.ci.yml down --remove-orphans || true
                    docker rm -f nids_redis_ci || true
                    docker compose -p nids_ci_${BUILD_NUMBER} -f docker-compose.ci.yml up -d --build --wait
                    docker compose -p nids_ci_${BUILD_NUMBER} -f docker-compose.ci.yml ps

                    echo "=== Resolving reachable Redis endpoint ==="
                    REDIS_TEST_HOST=$(venv/bin/python - <<'PY'
import socket
import subprocess
import sys
import time

port = 6380
candidates = ["localhost", "127.0.0.1", "host.docker.internal", "redis-ci", "redis"]

try:
    gateway = subprocess.check_output(
        "ip route | awk '/default/ {print $3; exit}'",
        shell=True,
        text=True,
    ).strip()
    if gateway:
        candidates.append(gateway)
except Exception:
    pass

deduped = []
for host in candidates:
    if host and host not in deduped:
        deduped.append(host)

deadline = time.time() + 60
while time.time() < deadline:
    for host in deduped:
        try:
            with socket.create_connection((host, port), timeout=2) as sock:
                sock.sendall(b"*1\\r\\n$4\\r\\nPING\\r\\n")
                reply = sock.recv(16)
                if reply.startswith(b"+PONG"):
                    print(host)
                    sys.exit(0)
        except OSError:
            continue
    time.sleep(2)

sys.exit(1)
PY
                    ) || {
                        echo "Redis on port 6380 is not reachable from Jenkins runtime"
                        docker compose -p nids_ci_${BUILD_NUMBER} -f docker-compose.ci.yml logs --tail=80 redis-ci || true
                        exit 1
                    }
                    echo "Using REDIS_HOST=${REDIS_TEST_HOST} REDIS_PORT=6380"

                    echo "=== Running integration tests ==="
                    REDIS_HOST=${REDIS_TEST_HOST} REDIS_PORT=6380 NIDS_DISABLE_CASSANDRA=1 NIDS_RUN_INTEGRATION=1 venv/bin/pytest tests/ -m integration \
                        --junitxml=integration-results.xml
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

        // ── STAGE 5 ──────────────────────────────────────────────────────────
        stage('Build Docker Image') {
            steps {
                sh '''
                    echo "=== Building Docker image: ${IMAGE_NAME}:${IMAGE_TAG} ==="
                    docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .
                    docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${IMAGE_NAME}:latest
                '''
            }
        }

        // ── STAGE 6 ──────────────────────────────────────────────────────────
        stage('Push Docker Image') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: "${DOCKER_CREDENTIALS_ID}",
                    usernameVariable: 'DOCKER_USER',
                    passwordVariable: 'DOCKER_PASS'
                )]) {
                    sh '''
                        echo "=== Logging in to Docker registry ==="
                        echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin

                        echo "=== Pushing ${DOCKER_USER}/${IMAGE_NAME}:${IMAGE_TAG} ==="
                        docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${DOCKER_USER}/${IMAGE_NAME}:${IMAGE_TAG}
                        docker push ${DOCKER_USER}/${IMAGE_NAME}:${IMAGE_TAG}

                        if [ "${GIT_BRANCH}" = "origin/master" ]; then
                            echo "=== Pushing ${DOCKER_USER}/${IMAGE_NAME}:latest ==="
                            docker tag ${IMAGE_NAME}:${IMAGE_TAG} ${DOCKER_USER}/${IMAGE_NAME}:latest
                            docker push ${DOCKER_USER}/${IMAGE_NAME}:latest
                        fi

                        docker logout
                    '''
                }
            }
        }

        // ── STAGE 7 ──────────────────────────────────────────────────────────
        // Only deploy when code is merged to 'master'
        // Feature branches just run stages 1-6 to verify they're safe to merge
        stage('Deploy') {
            when {
                expression { env.GIT_BRANCH == 'origin/master' }
            }
            steps {
                sh '''
                    echo "=== Deploying full stack with docker compose ==="
                    docker compose -f docker-compose.yml up -d --build --wait

                    echo "=== Stack is up ==="
                    docker compose -f docker-compose.yml ps
                '''
            }
            post {
                success {
                    echo "Deployment successful! Dashboard: http://localhost:5000"
                }
                failure {
                    sh 'docker compose -f docker-compose.yml logs --tail=50'
                }
            }
        }
    }

    // ── GLOBAL POST ACTIONS ──────────────────────────────────────────────────
    post {
        always {
            echo "Pipeline finished. Build #${BUILD_NUMBER} on branch ${env.BRANCH_NAME}"
        }
        failure {
            echo "BUILD FAILED — check the logs above."
            // You can add email/Slack notification here later:
            // mail to: 'your-team@example.com', subject: "NIDS Build Failed #${BUILD_NUMBER}"
        }
        success {
            echo "BUILD SUCCEEDED"
        }
        cleanup {
            // Remove the venv folder after the build to keep the workspace clean
            sh 'rm -rf venv'
        }
    }
}
