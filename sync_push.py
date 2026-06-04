"""
sync_push.py — NIDS Data Synchronization Script

Reads the latest alerts from local Redis and POSTs them to the EC2 dashboard
/api/ingest endpoint every 60 seconds.

Usage:
    python sync_push.py                          # Run once
    python sync_push.py --loop                   # Run every 60s
    python sync_push.py --loop --interval 30     # Custom interval

Environment variables:
    LOCAL_REDIS_HOST    Local Redis host (default: localhost)
    LOCAL_REDIS_PORT    Local Redis port (default: 6379)
    EC2_URL             EC2 dashboard base URL (default: http://localhost:5000)
    INGEST_TOKEN        Shared API key for /api/ingest (default: devops-demo)
    SYNC_SESSION_ID     Session ID to sync (default: local-session)
    SYNC_LIMIT          Max alerts per push (default: 500)
"""

import json
import os
import sys
import time
import argparse
from datetime import datetime, UTC

import redis
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOCAL_REDIS_HOST = os.getenv("LOCAL_REDIS_HOST", "localhost")
LOCAL_REDIS_PORT = int(os.getenv("LOCAL_REDIS_PORT", "6379"))
EC2_URL = os.getenv("EC2_URL", "http://localhost:5000").rstrip("/")
INGEST_TOKEN = os.getenv("INGEST_TOKEN", "devops-demo")
SESSION_ID = os.getenv("SYNC_SESSION_ID", "local-session")
SYNC_LIMIT = int(os.getenv("SYNC_LIMIT", "500"))
TIMEOUT = 15  # HTTP request timeout seconds


def connect_local_redis() -> redis.Redis:
    """Connect to local Redis with retry."""
    for attempt in range(5):
        try:
            client = redis.Redis(
                host=LOCAL_REDIS_HOST,
                port=LOCAL_REDIS_PORT,
                db=0,
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=5,
            )
            client.ping()
            print(f"[Sync] Connected to local Redis at {LOCAL_REDIS_HOST}:{LOCAL_REDIS_PORT}")
            return client
        except Exception as exc:
            print(f"[Sync] Redis connection attempt {attempt+1} failed: {exc}")
            time.sleep(3)
    raise RuntimeError("Could not connect to local Redis after 5 attempts")


def fetch_alerts(r: redis.Redis, session_id: str, limit: int) -> list:
    """Read latest alerts from local Redis."""
    key = f"nids:alerts:{session_id}"
    try:
        raw_rows = r.lrange(key, 0, limit - 1)
        alerts = []
        for row in raw_rows:
            try:
                alerts.append(json.loads(row))
            except json.JSONDecodeError:
                continue
        return alerts
    except redis.RedisError as exc:
        print(f"[Sync] Redis read error: {exc}")
        return []


def fetch_sessions(r: redis.Redis) -> list:
    """Read session metadata from local Redis."""
    key = "nids:sessions"
    try:
        raw = r.hvals(key)
        sessions = []
        for row in raw:
            try:
                sessions.append(json.loads(row))
            except json.JSONDecodeError:
                continue
        return sessions
    except redis.RedisError:
        return []


def push_to_ec2(alerts: list, sessions: list) -> bool:
    """POST alerts and sessions to EC2 /api/ingest."""
    if not alerts:
        print("[Sync] No alerts to push.")
        return True

    payload = {
        "session_id": SESSION_ID,
        "alerts": alerts,
        "sessions": sessions,
        "synced_at": datetime.now(UTC).isoformat(),
    }

    headers = {
        "Content-Type": "application/json",
        "X-Ingest-Token": INGEST_TOKEN,
    }

    url = f"{EC2_URL}/api/ingest"

    for attempt in range(3):
        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=TIMEOUT)
            if resp.status_code == 200:
                result = resp.json()
                print(f"[Sync] OK Pushed {len(alerts)} alerts -> EC2 | Response: {result}")
                return True
            else:
                print(f"[Sync] WARN EC2 returned HTTP {resp.status_code}: {resp.text[:200]}")
        except requests.RequestException as exc:
            print(f"[Sync] Attempt {attempt+1} failed: {exc}")
            if attempt < 2:
                time.sleep(5)

    print("[Sync] FAIL All 3 push attempts failed. Will retry next cycle.")
    return False


def run_once():
    """Run a single sync cycle."""
    print(f"\n[Sync] {datetime.now(UTC).isoformat()} — Starting sync...")
    r = connect_local_redis()
    alerts = fetch_alerts(r, SESSION_ID, SYNC_LIMIT)
    sessions = fetch_sessions(r)
    print(f"[Sync] Fetched {len(alerts)} alerts, {len(sessions)} sessions")
    success = push_to_ec2(alerts, sessions)
    r.close()
    return success


def main():
    parser = argparse.ArgumentParser(description="NIDS sync push to EC2")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=60, help="Sync interval in seconds")
    args = parser.parse_args()

    print("=" * 60)
    print("[Sync] NIDS -> EC2 Data Sync")
    print(f"  Local Redis:  {LOCAL_REDIS_HOST}:{LOCAL_REDIS_PORT}")
    print(f"  EC2 URL:      {EC2_URL}")
    print(f"  Session ID:   {SESSION_ID}")
    print(f"  Loop:         {args.loop}")
    print(f"  Interval:     {args.interval}s")
    print("=" * 60)

    if args.loop:
        while True:
            try:
                run_once()
            except KeyboardInterrupt:
                print("\n[Sync] Stopped by user.")
                sys.exit(0)
            except Exception as exc:
                print(f"[Sync] Unexpected error: {exc}")
            print(f"[Sync] Sleeping {args.interval}s...")
            time.sleep(args.interval)
    else:
        success = run_once()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
