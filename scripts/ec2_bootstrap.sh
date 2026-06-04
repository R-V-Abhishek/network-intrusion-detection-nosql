#!/bin/bash
# ec2_bootstrap.sh — One-time EC2 setup for NIDS Dashboard
# Compatible with Ubuntu 22.04, 24.04, and 26.04
#
# Usage (run as root or with sudo):
#   curl -fsSL https://raw.githubusercontent.com/R-V-Abhishek/network-intrusion-detection-nosql/master/scripts/ec2_bootstrap.sh | sudo bash
#
# Or with a custom token:
#   curl -fsSL .../ec2_bootstrap.sh | sudo INGEST_TOKEN=mysecret bash

set -euo pipefail

# ── Resolve real user even when running under sudo ────────────────────────────
REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME=$(eval echo "~$REAL_USER")

APP_DIR="${APP_DIR:-$REAL_HOME/nids-app}"
REPO_URL="${REPO_URL:-https://github.com/R-V-Abhishek/network-intrusion-detection-nosql.git}"
INGEST_TOKEN="${INGEST_TOKEN:-devops-demo}"

echo "=== NIDS EC2 Bootstrap ==="
echo "  Running as:   $REAL_USER"
echo "  App dir:      $APP_DIR"
echo "  Repo URL:     $REPO_URL"
echo ""

# ── 1. System packages ────────────────────────────────────────────────────────
echo "[1/5] Installing system packages..."
apt-get update -y
apt-get install -y git curl

# Install Docker only if not already present (avoids failures on Ubuntu 24/26)
if command -v docker >/dev/null 2>&1; then
    echo "  Docker already installed: $(docker --version)"
else
    echo "  Installing docker.io..."
    apt-get install -y docker.io
fi

systemctl enable docker
systemctl start docker

# Add real user to docker group so they can run docker without sudo
usermod -aG docker "${SUDO_USER:-$USER}" || true

# ── Detect docker compose variant ─────────────────────────────────────────────
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    echo "[ERROR] Neither 'docker compose' (plugin) nor 'docker-compose' (v1) found."
    echo "  Install with: apt-get install -y docker-compose-plugin"
    exit 1
fi
echo "  Compose command: $COMPOSE"

# ── 2. Clone or update repo ───────────────────────────────────────────────────
echo "[2/5] Cloning/updating repository..."
if [ ! -d "$APP_DIR/.git" ]; then
    git clone "$REPO_URL" "$APP_DIR"
    chown -R "$REAL_USER:$REAL_USER" "$APP_DIR"
fi

cd "$APP_DIR"
git fetch --all
git checkout master 2>/dev/null || git checkout main
git reset --hard "origin/$(git rev-parse --abbrev-ref HEAD)"

# ── 3. Start containers ───────────────────────────────────────────────────────
echo "[3/5] Starting Docker containers..."
INGEST_TOKEN="$INGEST_TOKEN" \
    $COMPOSE -f docker-compose.deploy.yml up -d --build

# ── 4. Health check (30 retries — image pull on t3.micro can be slow) ─────────
echo "[4/5] Waiting for dashboard to be healthy..."
HEALTHY=0
for i in $(seq 1 30); do
    STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/api/health --max-time 5 || echo "000")
    echo "  Attempt $i/30: HTTP $STATUS"
    if [ "$STATUS" = "200" ]; then
        echo "[4/5] Dashboard is healthy!"
        HEALTHY=1
        break
    fi
    sleep 10
done

if [ "$HEALTHY" -eq 0 ]; then
    echo "[WARNING] Dashboard did not respond after 30 attempts."
    echo "  Check logs: docker logs nids_app"
fi

# ── 5. Show status ────────────────────────────────────────────────────────────
echo "[5/5] Container status:"
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "=== Bootstrap complete ==="
PUBLIC_IP=$(curl -s --max-time 3 http://169.254.169.254/latest/meta-data/public-ipv4 || \
            curl -s --max-time 3 https://checkip.amazonaws.com || echo "<EC2_IP>")
echo "  Dashboard: http://$PUBLIC_IP"
echo "  Health:    http://$PUBLIC_IP/api/health"
echo ""
echo "  NOTE: Log out and back in (or run 'newgrp docker') for docker group to take effect."
echo ""
echo "To sync data from local machine:"
echo "  python sync_push.py --loop --interval 60"
