"""
Alert Storage Module for NIDS

Manages storage and retrieval of intrusion alerts using:
- Cassandra: Persistent storage for alerts, sessions, and stats
- Redis: Fast caching and pub/sub for real-time notifications

Provides:
- AlertStorage class with full CRUD operations
- Module-level session management helpers
"""

import os
import time
import json
import uuid
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

from cassandra.cluster import Cluster
from cassandra.auth import PlainTextAuthProvider
from cassandra.query import SimpleStatement
import redis

from config.config import CASSANDRA_CONFIG, REDIS_CONFIG, ALERT_CONFIG


class AlertStorage:
    """
    Storage layer for NIDS alerts using Cassandra + Redis.
    
    Cassandra: Long-term storage, complex queries
    Redis: Real-time pub/sub, fast recent alerts cache
    """
    
    def __init__(self):
        """Initialize connections to Cassandra and Redis."""
        self.cassandra_cluster = None
        self.cassandra_session = None
        self.redis_client = None
        self.keyspace = CASSANDRA_CONFIG["keyspace"]
    
    def connect(self, max_retries: int = 5) -> bool:
        """
        Connect to Cassandra and Redis with retry logic.
        
        Args:
            max_retries: Maximum number of connection attempts
            
        Returns:
            True if both connections successful, False otherwise
        """
        # Connect to Cassandra
        for attempt in range(max_retries):
            try:
                self.cassandra_cluster = Cluster(
                    contact_points=CASSANDRA_CONFIG["contact_points"],
                    port=CASSANDRA_CONFIG["port"]
                )
                self.cassandra_session = self.cassandra_cluster.connect()
                self.cassandra_session.set_keyspace(self.keyspace)
                print(f"[AlertStorage] Connected to Cassandra (keyspace: {self.keyspace})")
                break
            except Exception as e:
                print(f"[AlertStorage] Cassandra connection attempt {attempt + 1}/{max_retries} failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(5)
                else:
                    return False
        
        # Connect to Redis
        try:
            self.redis_client = redis.Redis(
                host=REDIS_CONFIG["host"],
                port=REDIS_CONFIG["port"],
                db=REDIS_CONFIG["db"],
                decode_responses=REDIS_CONFIG["decode_responses"]
            )
            self.redis_client.ping()
            print(f"[AlertStorage] Connected to Redis at {REDIS_CONFIG['host']}:{REDIS_CONFIG['port']}")
        except Exception as e:
            print(f"[AlertStorage] Redis connection failed: {e}")
            return False
        
        return True
    
    def store_alert(self, alert: Dict[str, Any], session_id: str) -> str:
        """
        Store an alert in Cassandra and Redis.
        
        Args:
            alert: Alert dictionary with keys like binary_prediction, attack_type, etc.
            session_id: Session identifier
            
        Returns:
            alert_id (UUID string)
        """
        alert_id = str(uuid.uuid4())
        alert_time = datetime.utcnow()
        
        # Insert into Cassandra intrusion_alerts table
        query = """
            INSERT INTO intrusion_alerts (
                session_id, alert_time, alert_id, binary_prediction, binary_probability,
                attack_type, attack_confidence, severity, src_ip, dst_ip,
                src_port, dst_port, protocol, sbytes, dbytes, rate, feature_vector, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        self.cassandra_session.execute(query, (
            session_id,
            alert_time,
            uuid.UUID(alert_id),
            alert.get("binary_prediction", 0),
            alert.get("binary_probability", 0.0),
            alert.get("attack_type", "Unknown"),
            alert.get("attack_confidence", 0.0),
            alert.get("severity", "low"),
            alert.get("src_ip", ""),
            alert.get("dst_ip", ""),
            alert.get("src_port", 0),
            alert.get("dst_port", 0),
            alert.get("protocol", ""),
            alert.get("sbytes", 0),
            alert.get("dbytes", 0),
            alert.get("rate", 0.0),
            alert.get("feature_vector", ""),
            alert_time
        ))
        
        # Update counter table for stats
        attack_type = alert.get("attack_type", "Unknown")
        severity = alert.get("severity", "low")
        counter_query = """
            UPDATE alert_stats_by_session
            SET alert_count = alert_count + 1
            WHERE session_id = %s AND attack_type = %s AND severity = %s
        """
        self.cassandra_session.execute(counter_query, (session_id, attack_type, severity))
        
        # Store in Redis sorted set (recent alerts cache)
        alert_json = json.dumps({
            "alert_id": alert_id,
            "session_id": session_id,
            "alert_time": alert_time.isoformat(),
            "attack_type": attack_type,
            "severity": severity,
            **alert
        })
        
        redis_key = ALERT_CONFIG["redis_key_recent"]
        self.redis_client.zadd(
            f"{redis_key}:{session_id}",
            {alert_json: alert_time.timestamp()}
        )
        
        # Publish to Redis channel for real-time notifications
        self.redis_client.publish(
            ALERT_CONFIG["redis_channel"],
            alert_json
        )
        
        return alert_id
    
    def get_alerts(
        self, 
        session_id: str, 
        limit: int = 100, 
        attack_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve alerts from Cassandra.
        
        Args:
            session_id: Session identifier
            limit: Maximum number of alerts to return
            attack_type: Optional filter by attack type
            
        Returns:
            List of alert dictionaries
        """
        if attack_type:
            query = """
                SELECT * FROM intrusion_alerts
                WHERE session_id = %s AND attack_type = %s
                ORDER BY alert_time DESC
                LIMIT %s
            """
            rows = self.cassandra_session.execute(query, (session_id, attack_type, limit))
        else:
            query = """
                SELECT * FROM intrusion_alerts
                WHERE session_id = %s
                ORDER BY alert_time DESC
                LIMIT %s
            """
            rows = self.cassandra_session.execute(query, (session_id, limit))
        
        alerts = []
        for row in rows:
            alerts.append({
                "session_id": row.session_id,
                "alert_time": row.alert_time.isoformat() if row.alert_time else None,
                "alert_id": str(row.alert_id),
                "binary_prediction": row.binary_prediction,
                "binary_probability": row.binary_probability,
                "attack_type": row.attack_type,
                "attack_confidence": row.attack_confidence,
                "severity": row.severity,
                "src_ip": row.src_ip,
                "dst_ip": row.dst_ip,
                "src_port": row.src_port,
                "dst_port": row.dst_port,
                "protocol": row.protocol,
                "sbytes": row.sbytes,
                "dbytes": row.dbytes,
                "rate": row.rate
            })
        
        return alerts
    
    def get_stats(self, session_id: str, hours: int = 24) -> Dict[str, Any]:
        """
        Get aggregated statistics from counter table.
        
        Args:
            session_id: Session identifier
            hours: Time window in hours (for filtering recent alerts)
            
        Returns:
            Dictionary with total counts, by severity, by attack type
        """
        query = """
            SELECT attack_type, severity, alert_count
            FROM alert_stats_by_session
            WHERE session_id = %s
        """
        rows = self.cassandra_session.execute(query, (session_id,))
        
        total = 0
        by_severity = {"low": 0, "medium": 0, "high": 0}
        by_type = {}
        
        for row in rows:
            count = row.alert_count
            total += count
            
            # Aggregate by severity
            if row.severity in by_severity:
                by_severity[row.severity] += count
            
            # Aggregate by attack type
            if row.attack_type not in by_type:
                by_type[row.attack_type] = 0
            by_type[row.attack_type] += count
        
        return {
            "total": total,
            "by_severity": by_severity,
            "by_type": by_type,
            "time_window_hours": hours
        }
    
    def get_timeline(
        self, 
        session_id: str, 
        hours: int = 24, 
        interval_mins: int = 60
    ) -> List[Dict[str, Any]]:
        """
        Get time-bucketed alert counts for timeline visualization.
        
        Args:
            session_id: Session identifier
            hours: Time window in hours
            interval_mins: Bucket interval in minutes
            
        Returns:
            List of {timestamp, count} dictionaries
        """
        # Use Redis sorted set for fast time-range queries
        redis_key = f"{ALERT_CONFIG['redis_key_recent']}:{session_id}"
        
        now = datetime.utcnow()
        start_time = now - timedelta(hours=hours)
        
        # Get alerts within time window
        alerts = self.redis_client.zrangebyscore(
            redis_key,
            start_time.timestamp(),
            now.timestamp()
        )
        
        # Bucket alerts by interval
        buckets = {}
        for alert_json in alerts:
            alert = json.loads(alert_json)
            alert_time = datetime.fromisoformat(alert["alert_time"])
            
            # Round down to interval boundary
            bucket_time = alert_time - timedelta(
                minutes=alert_time.minute % interval_mins,
                seconds=alert_time.second,
                microseconds=alert_time.microsecond
            )
            bucket_key = bucket_time.isoformat()
            
            if bucket_key not in buckets:
                buckets[bucket_key] = 0
            buckets[bucket_key] += 1
        
        # Convert to sorted list
        timeline = [
            {"timestamp": ts, "count": count}
            for ts, count in sorted(buckets.items())
        ]
        
        return timeline
    
    def register_session(self, session_id: str, dataset: str) -> None:
        """
        Register a new detection session.
        
        Args:
            session_id: Unique session identifier
            dataset: Dataset name (e.g., "unsw", "cicids")
        """
        query = """
            INSERT INTO sessions (session_id, dataset, start_time, status, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """
        now = datetime.utcnow()
        self.cassandra_session.execute(query, (
            session_id,
            dataset,
            now,
            "active",
            now
        ))
        
        # Store in Redis for fast access
        self.redis_client.set(f"session:current", session_id)
        self.redis_client.hset(f"session:{session_id}", mapping={
            "dataset": dataset,
            "start_time": now.isoformat(),
            "status": "active"
        })
    
    def get_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieve recent sessions.
        
        Args:
            limit: Maximum number of sessions to return
            
        Returns:
            List of session dictionaries
        """
        query = """
            SELECT session_id, dataset, start_time, end_time, total_records, total_alerts, status
            FROM sessions
            LIMIT %s
        """
        rows = self.cassandra_session.execute(query, (limit,))
        
        sessions = []
        for row in rows:
            sessions.append({
                "session_id": row.session_id,
                "dataset": row.dataset,
                "start_time": row.start_time.isoformat() if row.start_time else None,
                "end_time": row.end_time.isoformat() if row.end_time else None,
                "total_records": row.total_records,
                "total_alerts": row.total_alerts,
                "status": row.status
            })
        
        return sessions
    
    def delete_session(self, session_id: str) -> Dict[str, Any]:
        """
        Delete a session and all associated alerts.
        
        Args:
            session_id: Session identifier
            
        Returns:
            Dictionary with deletion status
        """
        # Delete from sessions table
        self.cassandra_session.execute(
            "DELETE FROM sessions WHERE session_id = %s",
            (session_id,)
        )
        
        # Delete all alerts for this session
        self.cassandra_session.execute(
            "DELETE FROM intrusion_alerts WHERE session_id = %s",
            (session_id,)
        )
        
        # Delete stats
        self.cassandra_session.execute(
            "DELETE FROM alert_stats_by_session WHERE session_id = %s",
            (session_id,)
        )
        
        # Delete from Redis
        redis_key = f"{ALERT_CONFIG['redis_key_recent']}:{session_id}"
        self.redis_client.delete(redis_key)
        self.redis_client.delete(f"session:{session_id}")
        
        return {
            "deleted": True,
            "session_id": session_id
        }
    
    def delete_all_sessions(self) -> Dict[str, Any]:
        """
        Delete all sessions and alerts (WARNING: irreversible).
        
        Returns:
            Dictionary with deletion counts
        """
        # Truncate all tables
        self.cassandra_session.execute("TRUNCATE intrusion_alerts")
        self.cassandra_session.execute("TRUNCATE sessions")
        self.cassandra_session.execute("TRUNCATE alert_stats_by_session")
        
        # Clear Redis
        for key in self.redis_client.scan_iter(f"{ALERT_CONFIG['redis_key_recent']}:*"):
            self.redis_client.delete(key)
        
        for key in self.redis_client.scan_iter("session:*"):
            self.redis_client.delete(key)
        
        return {
            "deleted": True,
            "message": "All sessions and alerts deleted"
        }
    
    def close(self) -> None:
        """Close Cassandra and Redis connections."""
        if self.cassandra_cluster:
            self.cassandra_cluster.shutdown()
            print("[AlertStorage] Cassandra connection closed")
        
        if self.redis_client:
            self.redis_client.close()
            print("[AlertStorage] Redis connection closed")


# ══════════════════════════════════════════════════════════════════════════
# MODULE-LEVEL SESSION HELPERS
# ══════════════════════════════════════════════════════════════════════════

_storage_instance: Optional[AlertStorage] = None


def _get_storage() -> AlertStorage:
    """Get or create singleton storage instance."""
    global _storage_instance
    if _storage_instance is None:
        _storage_instance = AlertStorage()
        _storage_instance.connect()
    return _storage_instance


def start_new_session(dataset: str = "unsw") -> str:
    """
    Start a new detection session.
    
    Args:
        dataset: Dataset name
        
    Returns:
        session_id (UUID string)
    """
    session_id = str(uuid.uuid4())
    storage = _get_storage()
    storage.register_session(session_id, dataset)
    print(f"[Session] Started new session: {session_id} (dataset: {dataset})")
    return session_id


def get_current_session_id() -> Optional[str]:
    """
    Get the current active session ID from Redis.
    
    Returns:
        session_id or None if no active session
    """
    storage = _get_storage()
    session_id = storage.redis_client.get("session:current")
    return session_id


def set_current_session_id(session_id: str) -> None:
    """
    Set the current active session ID.
    
    Args:
        session_id: Session identifier
    """
    storage = _get_storage()
    storage.redis_client.set("session:current", session_id)
    print(f"[Session] Current session set to: {session_id}")


def clear_session() -> None:
    """Clear the current session ID."""
    storage = _get_storage()
    storage.redis_client.delete("session:current")
    print("[Session] Cleared current session")
