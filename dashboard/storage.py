"""Storage abstraction: Cassandra for durability, Redis for fast serving, in-memory fallback.

Write path:  alert → Cassandra (durable) + Redis (fast cache)
Read path:   Redis → Cassandra fallback → in-memory last resort

All connections are optional; the system degrades gracefully when services
are unavailable.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
import json
from threading import Lock
from typing import Dict, List, Optional
import uuid

import redis

from config.config import CASSANDRA_CONFIG, REDIS_CONFIG

# ---------------------------------------------------------------------------
# Cassandra schema
# ---------------------------------------------------------------------------

_KEYSPACE_DDL = """
CREATE KEYSPACE IF NOT EXISTS nids
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}
"""

_ALERTS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS nids.alerts (
    session_id      text,
    alert_time      text,
    alert_id        text,
    attack_type     text,
    severity        text,
    src_ip          text,
    dst_ip          text,
    src_port        int,
    dst_port        int,
    protocol        text,
    binary_prediction   int,
    binary_probability  double,
    attack_confidence   double,
    sbytes          int,
    dbytes          int,
    rate            double,
    PRIMARY KEY (session_id, alert_time, alert_id)
) WITH CLUSTERING ORDER BY (alert_time DESC, alert_id ASC)
"""

_SESSIONS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS nids.sessions (
    session_id  text PRIMARY KEY,
    dataset     text,
    created_at  text
)
"""

_INSERT_ALERT_CQL = """
INSERT INTO nids.alerts (
    session_id, alert_time, alert_id,
    attack_type, severity, src_ip, dst_ip, src_port, dst_port, protocol,
    binary_prediction, binary_probability, attack_confidence,
    sbytes, dbytes, rate
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

_SELECT_ALERTS_CQL = """
SELECT * FROM nids.alerts WHERE session_id = ? LIMIT ?
"""

_INSERT_SESSION_CQL = """
INSERT INTO nids.sessions (session_id, dataset, created_at) VALUES (?, ?, ?)
"""

_DELETE_ALERTS_CQL = """
DELETE FROM nids.alerts WHERE session_id = ?
"""

_DELETE_SESSION_CQL = """
DELETE FROM nids.sessions WHERE session_id = ?
"""

# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------

_CURRENT_SESSION_ID = "local-session"


def start_new_session() -> str:
    """Start and return a new session id."""
    global _CURRENT_SESSION_ID
    _CURRENT_SESSION_ID = f"session-{uuid.uuid4().hex[:10]}"
    return _CURRENT_SESSION_ID


def get_current_session_id() -> str:
    """Return active session id."""
    return _CURRENT_SESSION_ID


def set_current_session_id(session_id: str) -> None:
    """Set active session id."""
    global _CURRENT_SESSION_ID
    _CURRENT_SESSION_ID = session_id


def clear_session() -> None:
    """Reset active session id."""
    global _CURRENT_SESSION_ID
    _CURRENT_SESSION_ID = "local-session"


# ---------------------------------------------------------------------------
# AlertStorage
# ---------------------------------------------------------------------------

class AlertStorage:
    """Cassandra + Redis backed store with in-memory fallback."""

    def __init__(self) -> None:
        self._alerts: Dict[str, List[dict]] = defaultdict(list)
        self._sessions: Dict[str, dict] = {}
        self._lock = Lock()
        self._redis: Optional[redis.Redis] = None
        self._cass = None           # cassandra.cluster.Session
        self._cass_cluster = None   # cassandra.cluster.Cluster
        self._cass_stmts: dict = {}

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _alerts_key(session_id: str) -> str:
        return f"nids:alerts:{session_id}"

    @staticmethod
    def _sessions_key() -> str:
        return "nids:sessions"

    def _using_redis(self) -> bool:
        return self._redis is not None

    def _using_cassandra(self) -> bool:
        return self._cass is not None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self, max_retries: int = 5) -> bool:
        """Connect to Redis and Cassandra; keeps fallback mode if either is unavailable."""
        self._connect_redis(max_retries)
        self._connect_cassandra()
        return True

    def _connect_redis(self, max_retries: int) -> None:
        last_error: Optional[Exception] = None
        for _ in range(max_retries):
            try:
                client = redis.Redis(
                    host=REDIS_CONFIG.get("host", "localhost"),
                    port=REDIS_CONFIG.get("port", 6379),
                    db=REDIS_CONFIG.get("db", 0),
                    decode_responses=True,
                    socket_connect_timeout=float(REDIS_CONFIG.get("socket_connect_timeout", 3)),
                    socket_timeout=float(REDIS_CONFIG.get("socket_timeout", 8)),
                )
                client.ping()
                self._redis = client
                print("[Storage] Connected to Redis")
                return
            except Exception as exc:
                last_error = exc
        print(f"[Storage] Redis unavailable, using fallback: {last_error}")

    def _connect_cassandra(self) -> None:
        import os
        if os.getenv("USE_CASSANDRA") != "true":
            print("[Storage] Skipping Cassandra connection")
            return
            
        try:
            from cassandra.cluster import Cluster

            cluster = Cluster(
                contact_points=CASSANDRA_CONFIG.get("contact_points", ["localhost"]),
                port=CASSANDRA_CONFIG.get("port", 9042),
                connect_timeout=5,
            )
            session = cluster.connect()

            session.execute(_KEYSPACE_DDL)
            session.set_keyspace("nids")
            session.execute(_ALERTS_TABLE_DDL)
            session.execute(_SESSIONS_TABLE_DDL)

            self._cass_stmts = {
                "insert_alert": session.prepare(_INSERT_ALERT_CQL),
                "select_alerts": session.prepare(_SELECT_ALERTS_CQL),
                "insert_session": session.prepare(_INSERT_SESSION_CQL),
                "delete_alerts": session.prepare(_DELETE_ALERTS_CQL),
                "delete_session": session.prepare(_DELETE_SESSION_CQL),
            }

            self._cass = session
            self._cass_cluster = cluster
            print("[Storage] Connected to Cassandra")
        except Exception as exc:
            print(f"[Storage] Cassandra unavailable, using fallback: {exc}")

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    def store_alerts(self, alerts: List[dict], session_id: str) -> List[str]:
        """Persist many alerts with Redis pipelining and graceful fallbacks."""
        if not alerts:
            return []

        ids: List[str] = []
        payloads: List[dict] = []
        for alert in alerts:
            alert_id = alert.get("alert_id") or str(uuid.uuid4())
            payload = dict(alert)
            payload["alert_id"] = alert_id
            payload["session_id"] = session_id
            payload.setdefault("alert_time", datetime.utcnow().isoformat())
            ids.append(alert_id)
            payloads.append(payload)

        if self._using_cassandra():
            for payload in payloads:
                try:
                    self._cass.execute(
                        self._cass_stmts["insert_alert"],
                        (
                            session_id,
                            payload["alert_time"],
                            payload["alert_id"],
                            str(payload.get("attack_type") or ""),
                            str(payload.get("severity") or ""),
                            str(payload.get("src_ip") or ""),
                            str(payload.get("dst_ip") or ""),
                            int(payload.get("src_port") or 0),
                            int(payload.get("dst_port") or 0),
                            str(payload.get("protocol") or ""),
                            int(payload.get("binary_prediction") or 0),
                            float(payload.get("binary_probability") or 0.0),
                            float(payload.get("attack_confidence") or 0.0),
                            int(payload.get("sbytes") or 0),
                            int(payload.get("dbytes") or 0),
                            float(payload.get("rate") or 0.0),
                        ),
                    )
                except Exception as exc:
                    print(f"[Storage] Cassandra write failed: {exc}")
                    self._cass = None
                    break

        if self._using_redis():
            key = self._alerts_key(session_id)
            try:
                pipe = self._redis.pipeline(transaction=False)
                for payload in payloads:
                    pipe.lpush(key, json.dumps(payload))
                pipe.ltrim(key, 0, 9999)
                pipe.execute()
                return ids
            except redis.RedisError as exc:
                # Retry once with a fresh connection before disabling Redis.
                print(f"[Storage] Redis write failed, retrying once: {exc}")
                self._connect_redis(max_retries=1)
                if self._using_redis():
                    try:
                        pipe = self._redis.pipeline(transaction=False)
                        for payload in payloads:
                            pipe.lpush(key, json.dumps(payload))
                        pipe.ltrim(key, 0, 9999)
                        pipe.execute()
                        return ids
                    except redis.RedisError as retry_exc:
                        print(f"[Storage] Redis retry failed, using fallback memory: {retry_exc}")
                self._redis = None

        with self._lock:
            self._alerts[session_id].extend(payloads)
        return ids

    def store_alert(self, alert: dict, session_id: str) -> str:
        """Persist one alert to Cassandra + Redis and return generated id."""
        return self.store_alerts([alert], session_id)[0]

    def get_alerts(self, session_id: str, limit: int = 100, attack_type: Optional[str] = None) -> List[dict]:
        """Fetch most recent alerts for a session (Redis → Cassandra → in-memory)."""
        # Try Redis
        if self._using_redis():
            key = self._alerts_key(session_id)
            try:
                fetch_n = limit * 5 if attack_type else limit
                raw_rows = self._redis.lrange(key, 0, max(fetch_n - 1, 0))
                rows = []
                for row in raw_rows:
                    try:
                        rows.append(json.loads(row))
                    except json.JSONDecodeError:
                        continue
                if attack_type:
                    rows = [r for r in rows if str(r.get("attack_type", "")).lower() == attack_type.lower()]
                return rows[:limit]
            except redis.RedisError as exc:
                print(f"[Storage] Redis read failed, trying Cassandra: {exc}")
                self._redis = None

        # Try Cassandra
        if self._using_cassandra():
            try:
                fetch_n = limit * 5 if attack_type else limit
                result = self._cass.execute(
                    self._cass_stmts["select_alerts"], (session_id, fetch_n)
                )
                rows = [
                    {
                        "alert_id": row.alert_id,
                        "session_id": row.session_id,
                        "alert_time": row.alert_time,
                        "attack_type": row.attack_type,
                        "severity": row.severity,
                        "src_ip": row.src_ip,
                        "dst_ip": row.dst_ip,
                        "src_port": row.src_port,
                        "dst_port": row.dst_port,
                        "protocol": row.protocol,
                        "binary_prediction": row.binary_prediction,
                        "binary_probability": row.binary_probability,
                        "attack_confidence": row.attack_confidence,
                        "sbytes": row.sbytes,
                        "dbytes": row.dbytes,
                        "rate": row.rate,
                    }
                    for row in result
                ]
                if attack_type:
                    rows = [r for r in rows if str(r.get("attack_type", "")).lower() == attack_type.lower()]
                return rows[:limit]
            except Exception as exc:
                print(f"[Storage] Cassandra read failed, using in-memory: {exc}")
                self._cass = None

        # In-memory fallback
        rows = list(self._alerts.get(session_id, []))
        rows.sort(key=lambda r: r.get("alert_time", ""), reverse=True)
        if attack_type:
            rows = [r for r in rows if str(r.get("attack_type", "")).lower() == attack_type.lower()]
        return rows[:limit]

    # ------------------------------------------------------------------
    # Analytics helpers
    # ------------------------------------------------------------------

    def get_stats(self, session_id: str, hours: int = 24) -> dict:
        """Return aggregate counts by severity and attack type."""
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        rows = [
            r
            for r in self.get_alerts(session_id=session_id, limit=10000)
            if _parse_iso(r.get("alert_time")) >= cutoff
        ]

        by_sev = Counter(r.get("severity", "unknown") for r in rows)
        by_type = Counter(r.get("attack_type", "Unknown") for r in rows)
        return {
            "total": len(rows),
            "by_severity": dict(by_sev),
            "by_attack_type": dict(by_type),
        }

    def get_timeline(self, session_id: str, hours: int = 24, interval_mins: int = 60) -> List[dict]:
        """Return a fixed-interval alert histogram for charts."""
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=hours)
        rows = [
            r
            for r in self.get_alerts(session_id=session_id, limit=10000)
            if _parse_iso(r.get("alert_time")) >= cutoff
        ]

        buckets: Dict[str, int] = defaultdict(int)
        for row in rows:
            ts = _parse_iso(row.get("alert_time"))
            minute = (ts.minute // interval_mins) * interval_mins
            bucket = ts.replace(minute=minute, second=0, microsecond=0).isoformat()
            buckets[bucket] += 1

        return [{"bucket": key, "count": buckets[key]} for key in sorted(buckets.keys())]

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def register_session(self, session_id: str, dataset: str) -> None:
        """Register session metadata."""
        payload = {
            "session_id": session_id,
            "dataset": dataset,
            "created_at": datetime.utcnow().isoformat(),
        }

        if self._using_cassandra():
            try:
                self._cass.execute(
                    self._cass_stmts["insert_session"],
                    (session_id, dataset, payload["created_at"]),
                )
            except Exception as exc:
                print(f"[Storage] Cassandra session write failed: {exc}")

        if self._using_redis():
            try:
                self._redis.hset(self._sessions_key(), session_id, json.dumps(payload))
                return
            except redis.RedisError:
                pass

        with self._lock:
            self._sessions[session_id] = payload

    def get_sessions(self, limit: int = 10) -> List[dict]:
        """Return most recent sessions."""
        if self._using_redis():
            try:
                raw = self._redis.hvals(self._sessions_key())
                values = []
                for row in raw:
                    try:
                        values.append(json.loads(row))
                    except json.JSONDecodeError:
                        continue
                values.sort(key=lambda r: r.get("created_at", ""), reverse=True)
                return values[:limit]
            except redis.RedisError:
                pass

        if self._using_cassandra():
            try:
                result = self._cass.execute("SELECT * FROM nids.sessions")
                values = [
                    {
                        "session_id": row.session_id,
                        "dataset": row.dataset,
                        "created_at": row.created_at,
                    }
                    for row in result
                ]
                values.sort(key=lambda r: r.get("created_at", ""), reverse=True)
                return values[:limit]
            except Exception:
                pass

        values = list(self._sessions.values())
        values.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        return values[:limit]

    def delete_session(self, session_id: str) -> dict:
        """Delete one session and its alerts."""
        removed_alerts = 0
        session_removed = False

        if self._using_cassandra():
            try:
                result = self._cass.execute(
                    self._cass_stmts["select_alerts"], (session_id, 100000)
                )
                removed_alerts += len(list(result))
                self._cass.execute(self._cass_stmts["delete_alerts"], (session_id,))
                self._cass.execute(self._cass_stmts["delete_session"], (session_id,))
                session_removed = True
            except Exception as exc:
                print(f"[Storage] Cassandra delete failed: {exc}")

        if self._using_redis():
            try:
                removed_alerts = int(self._redis.llen(self._alerts_key(session_id)))
                self._redis.delete(self._alerts_key(session_id))
                session_removed = self._redis.hdel(self._sessions_key(), session_id) > 0
            except redis.RedisError:
                pass
        else:
            with self._lock:
                removed_alerts += len(self._alerts.pop(session_id, []))
                session_removed = session_removed or (self._sessions.pop(session_id, None) is not None)

        return {
            "session_id": session_id,
            "removed_alerts": removed_alerts,
            "session_removed": session_removed,
        }

    def delete_all_sessions(self) -> dict:
        """Delete all session and alert data."""
        removed_sessions = 0
        removed_alerts = 0

        if self._using_cassandra():
            try:
                sessions = self.get_sessions(limit=100000)
                for s in sessions:
                    sid = s.get("session_id")
                    if sid:
                        result = self._cass.execute(
                            self._cass_stmts["select_alerts"], (sid, 100000)
                        )
                        removed_alerts += len(list(result))
                        self._cass.execute(self._cass_stmts["delete_alerts"], (sid,))
                self._cass.execute("TRUNCATE nids.sessions")
                removed_sessions += len(sessions)
            except Exception as exc:
                print(f"[Storage] Cassandra delete-all failed: {exc}")

        if self._using_redis():
            try:
                session_ids = [
                    s.get("session_id")
                    for s in self.get_sessions(limit=100000)
                    if s.get("session_id")
                ]
                for sid in session_ids:
                    removed_alerts += int(self._redis.llen(self._alerts_key(sid)))
                    self._redis.delete(self._alerts_key(sid))
                removed_sessions += int(self._redis.hlen(self._sessions_key()))
                self._redis.delete(self._sessions_key())
            except redis.RedisError:
                pass
        else:
            with self._lock:
                removed_sessions += len(self._sessions)
                removed_alerts += sum(len(v) for v in self._alerts.values())
                self._sessions.clear()
                self._alerts.clear()

        return {"removed_sessions": removed_sessions, "removed_alerts": removed_alerts}

    def close(self) -> None:
        """Close storage connections."""
        if self._redis is not None:
            try:
                self._redis.close()
            except Exception:
                pass
        if self._cass_cluster is not None:
            try:
                self._cass_cluster.shutdown()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_STORAGE = AlertStorage()


def get_storage() -> AlertStorage:
    """Return singleton storage instance."""
    return _STORAGE


def _parse_iso(value: Optional[str]) -> datetime:
    if not value:
        return datetime.utcfromtimestamp(0)
    try:
        return datetime.fromisoformat(value.replace("Z", ""))
    except ValueError:
        return datetime.utcfromtimestamp(0)
