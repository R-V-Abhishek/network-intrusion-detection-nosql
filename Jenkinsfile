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

        // Set this so tests don't try to connect to real Spark/Kafka/Cassandra
        STUB_MODELS = "true"
    }

    stages {

        // ── STAGE 1 ──────────────────────────────────────────────────────────
        stage('Checkout') {
            steps {
                // Jenkins does this automatically when using "Pipeline from SCM"
                // but keeping it explicit is good practice
                checkout scm
                echo "Code checked out from branch: ${env.BRANCH_NAME}"
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
            // If lint fails, mark the build as UNSTABLE (warning) not FAILED
            // Remove this block if you want lint failures to stop the pipeline
            post {
                failure {
                    echo "Lint issues found — fix them before merging!"
                }
            }
        }

        // ── STAGE 4 ──────────────────────────────────────────────────────────
        stage('Test') {
            steps {
                sh '''
                    echo "=== Running pytest ==="
                    venv/bin/pytest tests/ \
                        --verbose \
                        --tb=short \
                        --junitxml=test-results.xml
                '''
            }
            // Always publish test results so Jenkins shows pass/fail counts
            post {
                always {
                    junit 'test-results.xml'
                }
                failure {
                    echo "Tests FAILED — this code will NOT be deployed."
                }
                success {
                    echo "All tests passed!"
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
        // Only deploy when code is merged to 'main'
        // Feature branches just run stages 1-5 to verify they're safe to merge
        stage('Deploy') {
            when {
                branch 'main'
            }
            steps {
                sh '''
                    echo "=== Deploying full stack with docker compose ==="
                    docker compose -f docker-compose.yml up -d --build

                    echo "=== Waiting for services to be healthy ==="
                    sleep 20

                    echo "=== Stack is up ==="
                    docker compose ps
                '''
            }
            post {
                success {
                    echo "Deployment successful! Dashboard: http://localhost:5000"
                }
                failure {
                    sh 'docker compose logs --tail=50'
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
