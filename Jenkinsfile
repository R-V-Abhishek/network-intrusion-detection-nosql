/*
 * Jenkinsfile — Declarative Pipeline for NIDS DevOps Demo
 *
 *  1. Checkout         — pull latest code
 *  2. Install          — pip install (cached)
 *  3. Quality          — lint (flake8) + unit tests (pytest) in parallel
 *  4. Integration Tests— spin up CI compose stack, run integration suite
 *  5. Build            — docker build + tag
 *  6. Deploy           — docker compose up on EC2 (master only)
 *  7. Health Check     — smoke test deployed endpoint
 */

pipeline {

    agent any

    options {
        buildDiscarder(logRotator(numToKeepStr: '10', artifactNumToKeepStr: '3'))
        timeout(time: 30, unit: 'MINUTES')
    }

    environment {
        IMAGE_NAME = "nids-app"
        IMAGE_TAG  = "${BUILD_NUMBER}"

        STUB_MODELS = "true"
        REDIS_HOST  = "redis"
        REDIS_PORT  = "6380"
    }

    stages {

        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Install Dependencies') {
            options { timeout(time: 5, unit: 'MINUTES') }
            steps {
                sh '''
                    python3 -m venv venv
                    venv/bin/pip install --upgrade pip --cache-dir /tmp/pip-cache
                    venv/bin/pip install -r requirements.txt --cache-dir /tmp/pip-cache
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
                        failure { echo "Lint issues found." }
                    }
                }

                stage('Unit Tests + Coverage') {
                    options { timeout(time: 10, unit: 'MINUTES') }
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
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                sh '''
                    docker compose -p nids_ci_${BUILD_NUMBER} -f docker-compose.ci.yml down --remove-orphans || true
                    docker compose -p nids_ci_${BUILD_NUMBER} -f docker-compose.ci.yml up -d --build --wait

                    echo "Waiting for Redis..."
                    for i in $(seq 1 30); do
                        docker compose -p nids_ci_${BUILD_NUMBER} -f docker-compose.ci.yml exec -T redis-ci redis-cli ping && break
                        sleep 2
                    done

                    REDIS_HOST=localhost REDIS_PORT=6380 NIDS_DISABLE_CASSANDRA=1 NIDS_RUN_INTEGRATION=1 \
                        venv/bin/pytest tests/ -m integration --junitxml=integration-results.xml
                '''
            }
            post {
                always {
                    sh 'docker compose -p nids_ci_${BUILD_NUMBER} -f docker-compose.ci.yml down --remove-orphans || true'
                    junit allowEmptyResults: true, testResults: 'integration-results.xml'
                    archiveArtifacts artifacts: 'integration-results.xml', allowEmptyArchive: true, fingerprint: true
                }
            }
        }

        stage('Build Docker Image') {
            options { timeout(time: 10, unit: 'MINUTES') }
            steps {
                sh '''
                    docker build -t ${IMAGE_NAME}:${IMAGE_TAG} -t ${IMAGE_NAME}:latest .
                '''
            }
        }

        stage('Deploy') {
            when {
                expression { env.GIT_BRANCH == 'origin/master' }
            }
            options { timeout(time: 10, unit: 'MINUTES') }
            environment {
                EC2_KEY = credentials('ec2-ssh-key')
            }
            steps {
                sh '''
                    chmod 400 $EC2_KEY
                    ssh -o StrictHostKeyChecking=no -i $EC2_KEY ec2-user@52.66.67.1 bash -s << 'ENDSSH'
                        set -e
                        cd ~/ngd-app
                        git pull
                        DOCKER_BUILDKIT=0 docker compose -f docker-compose.deploy.yml down --remove-orphans
                        DOCKER_BUILDKIT=0 docker compose -f docker-compose.deploy.yml up -d --build
                        docker image prune -f
                        docker ps
ENDSSH
                '''
            }
            post {
                failure {
                    sh "ssh -o StrictHostKeyChecking=no -i $EC2_KEY ec2-user@52.66.67.1 'docker logs nids_app --tail 50' || true"
                }
            }
        }

        stage('Health Check') {
            when {
                expression { env.GIT_BRANCH == 'origin/master' }
            }
            options { timeout(time: 3, unit: 'MINUTES') }
            steps {
                sh '''
                    echo "Waiting for app to be ready..."
                    for i in $(seq 1 15); do
                        STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://52.66.67.1 || true)
                        if [ "$STATUS" = "200" ]; then
                            echo "Health check passed! HTTP $STATUS"
                            exit 0
                        fi
                        echo "Attempt $i: HTTP $STATUS — retrying in 10s..."
                        sleep 10
                    done
                    echo "Health check FAILED after all retries"
                    exit 1
                '''
            }
            post {
                success { echo "Deployment verified: http://52.66.67.1 is live." }
                failure  { echo "App not reachable post-deploy — check container logs." }
            }
        }
    }

    post {
        always {
            echo "Pipeline finished. Build #${BUILD_NUMBER} on branch ${env.BRANCH_NAME}"
        }
        success { echo "BUILD SUCCEEDED" }
        failure  { echo "BUILD FAILED" }
        cleanup {
            sh '''
                docker image ls --format '{{.Repository}}:{{.Tag}} {{.ID}}' \
                    | grep "^${IMAGE_NAME}:" \
                    | awk '{print $2}' \
                    | sort -u \
                    | xargs -r docker image rm -f || true
                docker image prune -f || true
            '''
            cleanWs()
        }
    }
}
