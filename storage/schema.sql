PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS vehicle_signals (
    id INTEGER PRIMARY KEY,
    vehicle_id TEXT NOT NULL,
    trip_id INTEGER,
    signal_name TEXT NOT NULL,
    timestamp TEXT NOT NULL,             -- ISO-8601 UTC 'YYYY-MM-DD HH:MM:SS'
    value REAL,                          -- NULL = missing sample (never 0)
    unit TEXT NOT NULL,
    source TEXT NOT NULL,
    quality_status TEXT NOT NULL DEFAULT 'good',  -- good|missing|stale|implausible|unit_converted|uncertain
    data_maturity TEXT NOT NULL,         -- simulated|replayed|real
    ingestion_timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_name_ts ON vehicle_signals(signal_name, timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_ts ON vehicle_signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_signals_trip ON vehicle_signals(trip_id);
CREATE INDEX IF NOT EXISTS idx_signals_name_ts_val ON vehicle_signals(signal_name, timestamp, value);
-- covering index: aggregates and gap detection read name/ts/unit/quality/value without table lookups
CREATE INDEX IF NOT EXISTS idx_signals_cover ON vehicle_signals(signal_name, timestamp, unit, quality_status, value);

CREATE TABLE IF NOT EXISTS vehicle_events (
    id INTEGER PRIMARY KEY,
    vehicle_id TEXT NOT NULL,
    trip_id INTEGER,
    event_type TEXT NOT NULL,
    severity TEXT NOT NULL,              -- info|warning|critical
    timestamp TEXT NOT NULL,
    source TEXT NOT NULL,
    description TEXT,
    data_maturity TEXT NOT NULL,
    signal_ref TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_type_ts ON vehicle_events(event_type, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_ts ON vehicle_events(timestamp);

CREATE TABLE IF NOT EXISTS trips (
    trip_id INTEGER PRIMARY KEY,
    vehicle_id TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    distance REAL NOT NULL,
    road_type TEXT NOT NULL,             -- city|highway|mixed
    energy_used REAL NOT NULL,
    scenario_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_trips_start ON trips(start_time);
CREATE INDEX IF NOT EXISTS idx_trips_road ON trips(road_type);

CREATE TABLE IF NOT EXISTS signal_dictionary (
    signal_name TEXT PRIMARY KEY,
    unit TEXT NOT NULL,
    description TEXT,
    valid_min REAL,
    valid_max REAL,
    source_mapping TEXT,
    conversion_rules TEXT
);

CREATE TABLE IF NOT EXISTS query_audit (
    id INTEGER PRIMARY KEY,
    timestamp TEXT NOT NULL,
    query_category TEXT,
    retrieval_status TEXT,
    duration_ms REAL,
    evidence_count INTEGER,
    model_used TEXT,
    validation_status TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON query_audit(timestamp);

CREATE TABLE IF NOT EXISTS scenario_ground_truth (
    scenario_id TEXT NOT NULL,
    gt_key TEXT NOT NULL,
    gt_value TEXT NOT NULL,
    notes TEXT,
    PRIMARY KEY (scenario_id, gt_key)
);
