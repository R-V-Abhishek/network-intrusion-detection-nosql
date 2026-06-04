/*
 * Jenkinsfile — NIDS DevOps Demo
 * Hybrid Local+EC2 architecture
 *
 * Stages:
 *  1. Checkout        — pull latest code + show git info
 *  2. Install         — pip install into venv (pip cache)
 *  3. Quality         — lint (flake8) + unit tests (pytest) in parallel
 *  4. Integration     — spin up CI Redis stack, run integration suite
 *  5. Clean           — prune stale Docker images
 *  6. Build           — docker build Dockerfile.ec2 → tagged image
 *  7. Deploy to EC2   — SSH git pull + docker compose up (master only)
 *  8. Health Check    — curl /api/health smoke test (master only)
 *  9. Rollback        — restore previous image on health-check failure
 */

pipeline {

    agent any

    options {
        buildDiscarder(logRotator(numToKeepStr: '10', artifactNumToKeepStr: '5'))
        timeout(time: 30, unit: 'MINUTES')
    }

    triggers {
        // SCM polling every 5 minutes as backup if webhook fails
        pollSCM('H/5 * * * *')
    }

    environment {
        IMAGE_NAME   = "nids-app"
        IMAGE_TAG    = "${BUILD_NUMBER}"

        // Injected by Jenkins — no plaintext secrets in SCM
        EC2_HOST     = credentials('ec2-host')         // EC2 public IP
        EC2_KEY      = credentials('ec2-ssh-key')      // SSH .pem file
        INGEST_TOKEN = credentials('ec2-ingest-token') // shared API key

        STUB_MODELS  = "true"
        REDIS_HOST   = "redis"
        REDIS_PORT   = "6380"
    }

    stages {

        stage('Checkout') {
            steps {
                deleteDir()
                checkout scm
                echo "Branch: ${env.GIT_BRANCH} | Commit: ${env.GIT_COMMIT?.take(8)}"
            }
        }

        stage('Install Dependencies') {
            options { timeout(time: 5, unit: 'MINUTES') }
            steps {
                sh '''
                    python3 -m venv venv
                    venv/bin/pip install --upgrade pip --cache-dir /tmp/pip-cache --quiet
                    venv/bin/pip install -r requirements.txt --cache-dir /tmp/pip-cache --quiet
                '''
            }
        }

        stage('Quality') {
            parallel {

                stage('Lint') {
                    options { timeout(time: 5, unit: 'MINUTES') }
                    steps {
                        sh '''
                            venv/bin/flake8 config/ src/ streaming/ dashboard/ tests/ \
                                --max-line-length=110 \
                                --exclude=venv \
                                --count
                        '''
                    }
                    post {
                        failure { echo "❌ Lint failed — fix code style issues." }
                    }
                }

                stage('Unit Tests + Coverage') {
                    options { timeout(time: 10, unit: 'MINUTES') }
                    steps {
                        sh '''
                            venv/bin/pytest tests/ \
                                --junitxml=test-results.xml \
                                --cov=. \
                                --cov-report=xml \
                                --cov-report=html:htmlcov \
                                -v
                        '''
                    }
                    post {
                        always {
                            junit 'test-results.xml'
                            publishCoverage adapters: [coberturaAdapter('coverage.xml')]
                            archiveArtifacts artifacts: 'test-results.xml,coverage.xml,htmlcov/**', fingerprint: true
                        }
                        failure { echo "❌ Unit tests FAILED — deployment blocked." }
                        success { echo "✅ All unit tests passed!" }
                    }
                }
            }
        }

        stage('Integration Tests') {
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                sh '''
                    docker compose -f docker-compose.ci.yml down --remove-orphans 2>/dev/null || true
                    docker rm -f nids_redis_ci 2>/dev/null || true
                    docker compose -p nids_ci_${BUILD_NUMBER} -f docker-compose.ci.yml up -d --build --wait

                    # Probe Redis with a PING to confirm reachability
                    REDIS_TEST_HOST=$(python3 - <<'PY'
import socket, sys, time
port = 6380
candidates = ["localhost", "127.0.0.1", "host.docker.internal"]
deadline = time.time() + 60
while time.time() < deadline:
    for h in candidates:
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
                        echo "Redis on port 6380 not reachable"
                        docker compose -p nids_ci_${BUILD_NUMBER} -f docker-compose.ci.yml logs --tail=80 || true
                        exit 1
                    }

                    REDIS_HOST=${REDIS_TEST_HOST} REDIS_PORT=6380 NIDS_DISABLE_CASSANDRA=1 NIDS_RUN_INTEGRATION=1 \
                        venv/bin/pytest tests/ -m integration --junitxml=integration-results.xml -v
                '''
            }
            post {
                always {
                    sh 'docker compose -p nids_ci_${BUILD_NUMBER} -f docker-compose.ci.yml down --remove-orphans 2>/dev/null || true'
                    junit allowEmptyResults: true, testResults: 'integration-results.xml'
                    archiveArtifacts artifacts: 'integration-results.xml', allowEmptyArchive: true, fingerprint: true
                }
            }
        }

        stage('Clean Docker Environment') {
            steps {
                sh '''
                    docker image prune -f || true
                    docker system df
                '''
            }
        }

        stage('Build Docker Image') {
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                sh '''
                    docker build \
                        --build-arg BUILD_NUMBER=${BUILD_NUMBER} \
                        --build-arg GIT_COMMIT=${GIT_COMMIT} \
                        -t ${IMAGE_NAME}:${IMAGE_TAG} \
                        -t ${IMAGE_NAME}:latest \
                        -f Dockerfile.ec2 \
                        .
                    docker image ls ${IMAGE_NAME}
                '''
            }
        }

        stage('Deploy to EC2') {
            when {
                branch 'master'
                expression { currentBuild.result == null || currentBuild.result == 'SUCCESS' }
            }
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                sh '''
                    chmod 400 $EC2_KEY
                    ssh -o StrictHostKeyChecking=no \
                        -o ConnectTimeout=15 \
                        -i $EC2_KEY ubuntu@${EC2_HOST} << 'EOF'
                        set -e
                        cd ~/nids-app

                        git fetch --all
                        git reset --hard origin/master

                        # Record previous image for rollback
                        OLD_IMAGE=$(docker inspect nids_app --format '{{.Config.Image}}' 2>/dev/null || echo "none")
                        echo "Previous image: $OLD_IMAGE"
                        echo $OLD_IMAGE > /tmp/nids_prev_image.txt

                        # Deploy new version
                        INGEST_TOKEN="${INGEST_TOKEN}" \
                        DOCKER_BUILDKIT=0 docker compose -f docker-compose.deploy.yml up -d --build --force-recreate
                        docker image prune -f
                        docker ps -a
EOF
                '''
            }
            post {
                success {
                    echo "✅ Deployment successful! Dashboard: http://${EC2_HOST}"
                }
                failure {
                    sh '''
                        ssh -o StrictHostKeyChecking=no -i $EC2_KEY ubuntu@${EC2_HOST} \
                            "docker logs nids_app --tail 100" || true
                    '''
                }
            }
        }

        stage('Health Check') {
            when { branch 'master' }
            options { timeout(time: 3, unit: 'MINUTES') }
            steps {
                sh '''
                    sleep 20
                    for i in 1 2 3 4 5; do
                        STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
                            http://${EC2_HOST}/api/health \
                            --max-time 10 || echo "000")
                        echo "Health check attempt $i: HTTP $STATUS"
                        if [ "$STATUS" = "200" ]; then
                            echo "✅ Health check PASSED"
                            exit 0
                        fi
                        sleep 10
                    done
                    echo "❌ Health check FAILED after 5 attempts"
                    exit 1
                '''
            }
            post {
                success { echo "✅ Deployment verified: http://${EC2_HOST} is live." }
                failure  { echo "❌ App not reachable post-deploy — rollback will fire." }
            }
        }

        stage('Rollback') {
            when {
                branch 'master'
                expression { currentBuild.result == 'FAILURE' }
            }
            steps {
                echo "🔄 Initiating rollback..."
                sh '''
                    ssh -o StrictHostKeyChecking=no -i $EC2_KEY ubuntu@${EC2_HOST} << 'EOF'
                        PREV_IMAGE=$(cat /tmp/nids_prev_image.txt 2>/dev/null || echo "none")
                        echo "Rolling back to: $PREV_IMAGE"
                        if [ "$PREV_IMAGE" != "none" ] && [ -n "$PREV_IMAGE" ]; then
                            docker stop nids_app 2>/dev/null || true
                            docker run -d \
                                --name nids_app_rollback \
                                --network nids_net \
                                -p 80:5000 \
                                -e NIDS_DISABLE_CASSANDRA=1 \
                                -e REDIS_HOST=redis \
                                $PREV_IMAGE
                            echo "✅ Rollback complete"
                        else
                            echo "No previous image to roll back to"
                        fi
EOF
                '''
            }
        }
    }

    post {
        always {
            echo "Pipeline finished. Build #${BUILD_NUMBER} on ${env.BRANCH_NAME}"
            sh 'rm -rf venv || true'
        }
        failure {
            echo "❌ BUILD FAILED — Check console output above"
        }
        success {
            echo "✅ BUILD SUCCEEDED — All stages passed"
        }
        cleanup {
            sh '''
                docker image ls --format '{{.Repository}}:{{.Tag}} {{.ID}}' \
                    | grep '^nids-app:' \
                    | tail -n +4 \
                    | awk '{print $2}' \
                    | xargs -r docker image rm -f || true
                docker image prune -f || true
            '''
            cleanWs()
        }
    }
}
