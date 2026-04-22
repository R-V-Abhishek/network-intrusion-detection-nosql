# Jenkins DevOps Setup Guide

This guide explains how to set up the Jenkins CI/CD pipeline for this project using a Docker container.

## 1. Start Jenkins Container

A custom `Dockerfile.jenkins` is provided. Build and run it:

```bash
docker build -t custom-jenkins -f Dockerfile.jenkins .

docker run -d \
  --name jenkins \
  -p 8080:8080 -p 50000:50000 \
  -v jenkins_home:/var/jenkins_home \
  -v /var/run/docker.sock:/var/run/docker.sock \
  custom-jenkins
```

## 2. Initial Setup

Unlock Jenkins:
```bash
docker exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

1. Go to `http://localhost:8080`.
2. Paste the password.
3. Choose **Install suggested plugins**.
4. Create your admin user.

## 3. Required Plugins

Ensure the following plugins are installed (Manage Jenkins > Plugins):
*   **Git plugin**
*   **Pipeline**
*   **JUnit**
*   **Cobertura Plugin** (for coverage reports)

## 4. Create the Pipeline Job

1. Click **New Item** -> **Pipeline** -> Name it `nids-pipeline`.
2. Under **Build Triggers**, select **Poll SCM** and enter `* * * * *` (polls every minute).
3. Under **Pipeline**, select **Pipeline script from SCM**.
4. SCM: **Git**
5. Repository URL: (Your repo URL)
6. Branch Specifier: `*/master`
7. Script Path: `Jenkinsfile`
8. Click **Save**.

## 5. Known Issues

*   **Docker socket permissions:** The Jenkins user needs access to `/var/run/docker.sock`. The provided `Dockerfile.jenkins` adds the `jenkins` user to the `docker` group.
*   **Volume mounts in CI:** Avoid local bind-mounts like `./src:/app/src` in `docker-compose.yml` when deploying from Jenkins, as the host paths inside Jenkins refer to the Jenkins workspace, not the host machine, which leads to `No such file or directory` errors.
