-- 36 Chambers Knowledge Observatory
-- Dedicated analytical database. Do not run these tables inside Chroma internals.
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS inventory_snapshots (
  snapshot_id TEXT PRIMARY KEY,
  captured_at TEXT NOT NULL,
  scanner_version TEXT,
  host_name TEXT,
  notes TEXT
);

CREATE TABLE IF NOT EXISTS knowledge_assets (
  asset_id TEXT PRIMARY KEY,
  resource_id TEXT,
  chamber_id INTEGER NOT NULL,
  asset_type TEXT NOT NULL,
  physical_path TEXT,
  logical_id TEXT,
  content_hash TEXT,
  size_bytes INTEGER,
  created_at TEXT,
  modified_at TEXT,
  indexed_at TEXT,
  last_verified_at TEXT,
  embedding_model TEXT,
  source_version TEXT,
  sensitivity TEXT DEFAULT 'internal',
  retention_class TEXT DEFAULT 'UNCLASSIFIED',
  owner TEXT,
  UNIQUE(chamber_id, physical_path, logical_id)
);

CREATE TABLE IF NOT EXISTS asset_snapshot_stats (
  snapshot_id TEXT NOT NULL REFERENCES inventory_snapshots(snapshot_id),
  asset_id TEXT NOT NULL REFERENCES knowledge_assets(asset_id),
  exists_flag INTEGER NOT NULL,
  size_bytes INTEGER,
  record_count INTEGER,
  chunk_count INTEGER,
  collection_name TEXT,
  modified_at TEXT,
  PRIMARY KEY(snapshot_id, asset_id)
);

CREATE TABLE IF NOT EXISTS agent_events (
  event_id TEXT PRIMARY KEY,
  event_time TEXT NOT NULL,
  request_id TEXT NOT NULL,
  agent_name TEXT NOT NULL,
  app_name TEXT,
  chamber_id INTEGER,
  resource_id TEXT,
  action TEXT NOT NULL,
  status TEXT NOT NULL,
  latency_ms REAL,
  error_class TEXT,
  model TEXT,
  task_type TEXT
);

CREATE TABLE IF NOT EXISTS retrieval_events (
  event_id TEXT PRIMARY KEY,
  event_time TEXT NOT NULL,
  request_id TEXT NOT NULL,
  agent_name TEXT NOT NULL,
  chamber_id INTEGER NOT NULL,
  resource_id TEXT,
  asset_id TEXT,
  document_id TEXT,
  chunk_id TEXT,
  retrieval_method TEXT,
  rank INTEGER,
  score REAL,
  included_in_prompt INTEGER DEFAULT 0,
  cited_in_answer INTEGER DEFAULT 0,
  source_modified_at TEXT,
  indexed_at TEXT,
  embedding_model TEXT,
  token_count INTEGER
);

CREATE TABLE IF NOT EXISTS asset_reviews (
  asset_id TEXT NOT NULL REFERENCES knowledge_assets(asset_id),
  reviewed_at TEXT NOT NULL,
  reviewer TEXT NOT NULL,
  classification TEXT NOT NULL,
  reason TEXT,
  action_taken TEXT,
  PRIMARY KEY(asset_id, reviewed_at)
);

CREATE INDEX IF NOT EXISTS idx_agent_events_time ON agent_events(event_time);
CREATE INDEX IF NOT EXISTS idx_agent_events_chamber ON agent_events(chamber_id, event_time);
CREATE INDEX IF NOT EXISTS idx_retrieval_events_doc ON retrieval_events(document_id, event_time);
CREATE INDEX IF NOT EXISTS idx_retrieval_events_chamber ON retrieval_events(chamber_id, event_time);
CREATE INDEX IF NOT EXISTS idx_assets_chamber ON knowledge_assets(chamber_id);
