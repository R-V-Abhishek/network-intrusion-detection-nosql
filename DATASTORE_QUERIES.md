# Datastore Queries for NIDS

This file documents the Cassandra CQL and Redis commands used by this project.
All entries below are taken from the active storage implementation in `dashboard/storage.py`.

## Cassandra (CQL)

### Schema and bootstrap queries

1. Create keyspace for persistent IDS data.

```sql
CREATE KEYSPACE IF NOT EXISTS nids
WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1}
```

What it does:
- Creates the `nids` keyspace if it does not already exist.
- Uses single-node friendly replication for local/demo deployments.

2. Create alerts table.

```sql
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
```

What it does:
- Stores intrusion alerts durably.
- Partitions by `session_id` and sorts newest alerts first by `alert_time`.

3. Create sessions table.

```sql
CREATE TABLE IF NOT EXISTS nids.sessions (
    session_id  text PRIMARY KEY,
    dataset     text,
    created_at  text
)
```

What it does:
- Stores dashboard session metadata used by settings/session APIs.

### Prepared/operational queries

4. Insert an alert.

```sql
INSERT INTO nids.alerts (
    session_id, alert_time, alert_id,
    attack_type, severity, src_ip, dst_ip, src_port, dst_port, protocol,
    binary_prediction, binary_probability, attack_confidence,
    sbytes, dbytes, rate
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
```

What it does:
- Persists each detected attack event.
- Called in the alert write path.

5. Read alerts by session.

```sql
SELECT * FROM nids.alerts WHERE session_id = ? LIMIT ?
```

What it does:
- Fetches recent alerts for dashboard/API reads.
- Also used before delete operations to count removed alerts.

6. Insert a session record.

```sql
INSERT INTO nids.sessions (session_id, dataset, created_at) VALUES (?, ?, ?)
```

What it does:
- Registers a new active session and its source dataset.

7. Delete all alerts in a session.

```sql
DELETE FROM nids.alerts WHERE session_id = ?
```

What it does:
- Clears all alert rows for one session during session deletion.

8. Delete one session.

```sql
DELETE FROM nids.sessions WHERE session_id = ?
```

What it does:
- Removes session metadata for one session.

9. Read all sessions.

```sql
SELECT * FROM nids.sessions
```

What it does:
- Loads all sessions to support session list APIs and bulk deletion.

10. Delete all sessions quickly.

```sql
TRUNCATE nids.sessions
```

What it does:
- Removes all rows in the sessions table during global cleanup.

## Redis (command-level operations)

Redis is used as a speed layer over Cassandra. In this project, commands are invoked through the Python Redis client API.

### Connection/health

1. `PING`

What it does:
- Verifies Redis connectivity during startup.

### Alert cache (list per session)

Key format:
- `nids:alerts:<session_id>`

2. `LPUSH nids:alerts:<session_id> <json-alert>`

What it does:
- Pushes newest alerts to the head of the per-session alert list.

3. `LTRIM nids:alerts:<session_id> 0 9999`

What it does:
- Caps each session list at 10,000 most recent entries to bound memory usage.

4. `LRANGE nids:alerts:<session_id> 0 <n>`

What it does:
- Reads most recent alerts for dashboard/API responses.

5. `LLEN nids:alerts:<session_id>`

What it does:
- Counts cached alerts when reporting delete totals.

6. `DEL nids:alerts:<session_id>`

What it does:
- Removes cached alerts for a session.

### Session cache (hash)

Key name:
- `nids:sessions`

7. `HSET nids:sessions <session_id> <json-session>`

What it does:
- Stores session metadata payloads by session id.

8. `HVALS nids:sessions`

What it does:
- Reads all cached session payloads for the session list API.

9. `HDEL nids:sessions <session_id>`

What it does:
- Removes one cached session.

10. `HLEN nids:sessions`

What it does:
- Counts cached sessions during bulk delete.

11. `DEL nids:sessions`

What it does:
- Clears all cached session metadata.

## Where this maps in the project

- Write path: `streaming/pipeline_runner.py` -> `dashboard/storage.py::store_alerts` (Cassandra + Redis)
- Read path: Flask APIs in `dashboard/api_alerts.py` and `dashboard/api_analytics.py` -> `dashboard/storage.py::get_alerts`
- Session path: settings APIs in dashboard app -> `dashboard/storage.py::register_session`, `get_sessions`, `delete_session`, `delete_all_sessions`