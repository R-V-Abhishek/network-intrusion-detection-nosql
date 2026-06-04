#!/bin/bash
# ec2_bootstrap.sh — One-time EC2 setup for NIDS Dashboard
# Run on a fresh Ubuntu 22.04 t3.micro instance:
#   curl -fsSL https://raw.githubusercontent.com/R-V-Abhishek/network-intrusion-detection-nosql/master/scripts/ec2_bootstrap.sh | bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/nids-app}"
REPO_URL="${REPO_URL:-https://github.com/R-V-Abhishek/network-intrusion-detection-nosql.git}"
INGEST_TOKEN="${INGEST_TOKEN:-devops-demo}"

echo "=== NIDS EC2 Bootstrap ==="
echo "  App dir:  $APP_DIR"
echo "  Repo URL: $REPO_URL"
echo ""

# ── 1. System packages ───────────────────────────────────────────────────────
echo "[1/5] Installing system packages..."
apt-get update -y
apt-get install -y docker.io docker-compose-plugin git curl

systemctl enable docker
systemctl start docker

# Allow current user to run docker without sudo
usermod -aG docker "$USER" || true

# ── 2. Clone or update repo ──────────────────────────────────────────────────
echo "[2/5] Cloning/updating repository..."
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
git fetch --all
git checkout master || git checkout main
git reset --hard origin/master

# ── 3. Start containers ──────────────────────────────────────────────────────
echo "[3/5] Starting Docker containers..."
INGEST_TOKEN="$INGEST_TOKEN" \
  docker compose -f docker-compose.deploy.yml up -d --build

# ── 4. Health check ──────────────────────────────────────────────────────────
echo "[4/5] Waiting for dashboard to be healthy..."
for i in $(seq 1 10); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost/api/health --max-time 5 || echo "000")
  echo "  Attempt $i: HTTP $STATUS"
  if [ "$STATUS" = "200" ]; then
    echo "[4/5] ✅ Dashboard is healthy!"
    break
  fi
  sleep 5
done

# ── 5. Show status ───────────────────────────────────────────────────────────
echo "[5/5] Container status:"
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "=== Bootstrap complete ==="
echo "Dashboard: http://$(curl -s http://169.254.169.254/latest/meta-data/public-ipv4 || echo '<EC2_IP>')"
echo ""
echo "To sync data from local machine:"
echo "  python sync_push.py --loop --interval 60"
