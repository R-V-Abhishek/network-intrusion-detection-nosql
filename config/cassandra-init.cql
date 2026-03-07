-- ══════════════════════════════════════════════════════════════════════════
-- Cassandra Schema for NIDS (Network Intrusion Detection System)
-- ══════════════════════════════════════════════════════════════════════════

-- Create keyspace if it doesn't exist
CREATE KEYSPACE IF NOT EXISTS nids
WITH replication = {
    'class': 'SimpleStrategy',
    'replication_factor': 1
};

USE nids;

-- ──────────────────────────────────────────────────────────────────────────
-- TABLE: intrusion_alerts
-- Stores individual alerts detected by the ML pipeline
-- Partition key: session_id (groups all alerts from the same session)
-- Clustering key: alert_time DESC (newest alerts first)
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS intrusion_alerts (
    session_id TEXT,
    alert_time TIMESTAMP,
    alert_id UUID,
    binary_prediction INT,
    binary_probability DOUBLE,
    attack_type TEXT,
    attack_confidence DOUBLE,
    severity TEXT,
    src_ip TEXT,
    dst_ip TEXT,
    src_port INT,
    dst_port INT,
    protocol TEXT,
    sbytes BIGINT,
    dbytes BIGINT,
    rate DOUBLE,
    feature_vector TEXT,
    created_at TIMESTAMP,
    PRIMARY KEY (session_id, alert_time, alert_id)
) WITH CLUSTERING ORDER BY (alert_time DESC, alert_id ASC);

-- Create index for querying by attack type
CREATE INDEX IF NOT EXISTS idx_attack_type ON intrusion_alerts (attack_type);

-- Create index for querying by severity
CREATE INDEX IF NOT EXISTS idx_severity ON intrusion_alerts (severity);

-- ──────────────────────────────────────────────────────────────────────────
-- TABLE: sessions
-- Stores metadata about detection sessions
-- Partition key: session_id
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    dataset TEXT,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    total_records BIGINT,
    total_alerts BIGINT,
    status TEXT,
    created_at TIMESTAMP
);

-- ──────────────────────────────────────────────────────────────────────────
-- TABLE: alert_stats_by_session
-- Counter table for fast aggregation queries
-- Stores counts by session and attack type for quick stats retrieval
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_stats_by_session (
    session_id TEXT,
    attack_type TEXT,
    severity TEXT,
    alert_count COUNTER,
    PRIMARY KEY (session_id, attack_type, severity)
);

-- ──────────────────────────────────────────────────────────────────────────
-- TABLE: timeline_stats
-- Stores time-bucketed alert counts for timeline queries
-- ──────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS timeline_stats (
    session_id TEXT,
    time_bucket TIMESTAMP,
    attack_type TEXT,
    alert_count COUNTER,
    PRIMARY KEY (session_id, time_bucket, attack_type)
) WITH CLUSTERING ORDER BY (time_bucket DESC, attack_type ASC);
