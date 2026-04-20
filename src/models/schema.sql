CREATE TABLE IF NOT EXISTS competitors (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parent_group TEXT,
    tier INTEGER NOT NULL,
    ico TEXT,
    config_path TEXT
);

CREATE TABLE IF NOT EXISTS signals (
    id TEXT PRIMARY KEY,
    competitor_id TEXT NOT NULL REFERENCES competitors(id),
    source TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT,
    url TEXT,
    detected_at TEXT NOT NULL,
    published_at TEXT,
    severity INTEGER DEFAULT 1,
    tags TEXT,
    metadata TEXT,
    change_summary TEXT,
    content_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signals_competitor ON signals(competitor_id);
CREATE INDEX IF NOT EXISTS idx_signals_source ON signals(source);
CREATE INDEX IF NOT EXISTS idx_signals_detected ON signals(detected_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_signals_hash ON signals(content_hash);
CREATE INDEX IF NOT EXISTS idx_signals_severity ON signals(severity);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    competitor_id TEXT NOT NULL REFERENCES competitors(id),
    source TEXT NOT NULL,
    snapshot_key TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    UNIQUE(competitor_id, source, snapshot_key, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_lookup
    ON snapshots(competitor_id, source, snapshot_key);

CREATE TABLE IF NOT EXISTS collector_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collector_name TEXT NOT NULL,
    competitor_id TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    signals_found INTEGER DEFAULT 0,
    error_message TEXT
);
