-- ============================================================
-- claude-master brain system: Authoritative SQLite Schema
-- Version: 0.1.0
-- Owner: contracts/ (frozen after Wave 0)
-- Python owns all brain_* tables.
-- Go writes only to: request_log, key_state.
-- TypeScript never touches this database.
-- ============================================================

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- ============================================================
-- BRAIN NODES (Python owner)
-- Represents concepts, code files, symbols, rules, skills, reflections.
-- ============================================================
CREATE TABLE IF NOT EXISTS brain_nodes (
    id               TEXT    NOT NULL PRIMARY KEY,
    node_type        TEXT    NOT NULL,   -- concept|file|symbol|rule|skill|reflection
    name             TEXT    NOT NULL,
    content          TEXT,
    tags             TEXT    DEFAULT '[]',   -- JSON array
    difficulty       REAL    NOT NULL DEFAULT 0.3,  -- FSRS D
    stability        REAL    NOT NULL DEFAULT 1.0,  -- FSRS S (days)
    last_accessed_at INTEGER NOT NULL,
    created_at       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brain_nodes_type     ON brain_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_brain_nodes_accessed ON brain_nodes(last_accessed_at DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS brain_nodes_fts
    USING fts5(id UNINDEXED, name, content, tokenize='porter ascii');

-- ============================================================
-- BRAIN EDGES – bi-temporal weighted directed synaptic graph (Python owner)
-- ============================================================
CREATE TABLE IF NOT EXISTS brain_edges (
    id            TEXT    NOT NULL PRIMARY KEY,
    source_id     TEXT    NOT NULL REFERENCES brain_nodes(id) ON DELETE CASCADE,
    target_id     TEXT    NOT NULL REFERENCES brain_nodes(id) ON DELETE CASCADE,
    relation_type TEXT    NOT NULL,  -- causes|reinforces|defines|depends_on|contradicts|lateral
    weight        REAL    NOT NULL DEFAULT 0.5,
    valid_at      INTEGER NOT NULL,
    invalid_at    INTEGER,           -- NULL = still active
    expired_at    INTEGER,
    access_count  INTEGER NOT NULL DEFAULT 1,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_brain_edges_source ON brain_edges(source_id) WHERE invalid_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_brain_edges_target ON brain_edges(target_id) WHERE invalid_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_brain_edges_weight ON brain_edges(weight DESC) WHERE invalid_at IS NULL;

-- NOTE: brain_node_vectors virtual table is created at runtime after
-- sqlite-vec extension load:
--   CREATE VIRTUAL TABLE brain_node_vectors USING vec0(
--       node_id TEXT PRIMARY KEY,
--       embedding float[384] distance_metric=cosine
--   );

-- ============================================================
-- EPISODIC EVENTS – hippocampal fast buffer (Python owner)
-- ============================================================
CREATE TABLE IF NOT EXISTS episodic_events (
    event_id       INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    session_id     TEXT    NOT NULL,
    event_type     TEXT    NOT NULL,  -- prompt|pre_tool|post_tool|test_result|reflection|sleep
    tool_name      TEXT,
    action_payload TEXT    NOT NULL,  -- JSON; NEVER store raw secrets
    outcome_reward REAL,              -- R in [-1, +1]; NULL = not evaluated
    source_node_id TEXT    REFERENCES brain_nodes(id),
    created_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_episodic_session ON episodic_events(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodic_type    ON episodic_events(event_type, created_at DESC);

-- ============================================================
-- MODEL STATS – Thompson Sampling bandit state (Python owner)
-- ============================================================
CREATE TABLE IF NOT EXISTS model_stats (
    model_id         TEXT NOT NULL PRIMARY KEY,
    provider         TEXT NOT NULL,
    successes        INTEGER NOT NULL DEFAULT 0,
    failures         INTEGER NOT NULL DEFAULT 0,
    total_latency_ms REAL    NOT NULL DEFAULT 0.0,
    total_tokens     INTEGER NOT NULL DEFAULT 0,
    last_used_at     INTEGER,
    updated_at       INTEGER NOT NULL
);

-- ============================================================
-- KEY STATE – per-key cooldown (Go owner; Go is the only writer)
-- ============================================================
CREATE TABLE IF NOT EXISTS key_state (
    key_hash       TEXT NOT NULL PRIMARY KEY,  -- SHA-256 of key prefix; never raw key
    provider       TEXT NOT NULL,
    account_label  TEXT NOT NULL DEFAULT '',
    is_active      INTEGER NOT NULL DEFAULT 1,
    cooldown_until INTEGER,
    failure_count  INTEGER NOT NULL DEFAULT 0,
    last_429_at    INTEGER,
    updated_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_key_state_provider ON key_state(provider, is_active);

-- ============================================================
-- REQUEST LOG – gateway audit (Go owner; Go is the only writer)
-- ============================================================
CREATE TABLE IF NOT EXISTS request_log (
    request_id    TEXT NOT NULL PRIMARY KEY,
    session_id    TEXT,
    model_id      TEXT NOT NULL,
    provider      TEXT NOT NULL,
    key_hash      TEXT NOT NULL,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    latency_ms    REAL,
    http_status   INTEGER NOT NULL,
    outcome       TEXT NOT NULL DEFAULT 'pending',  -- success|error|rate_limited|timeout
    privacy_class TEXT NOT NULL DEFAULT 'internal', -- internal|public
    created_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_request_log_session ON request_log(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_request_log_model   ON request_log(model_id, created_at DESC);

-- ============================================================
-- LESSONS – distilled operational rules (Python owner)
-- ============================================================
CREATE TABLE IF NOT EXISTS lessons (
    lesson_id      TEXT NOT NULL PRIMARY KEY,
    rule_text      TEXT NOT NULL,
    usage_count    INTEGER NOT NULL DEFAULT 0,
    reinforcements INTEGER NOT NULL DEFAULT 0,
    removals       INTEGER NOT NULL DEFAULT 0,
    confidence     REAL    NOT NULL DEFAULT 0.5,
    source_task_ids TEXT NOT NULL DEFAULT '[]',   -- JSON array of session_ids
    created_at     INTEGER NOT NULL,
    updated_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lessons_confidence ON lessons(confidence DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS lessons_fts
    USING fts5(lesson_id UNINDEXED, rule_text, tokenize='porter ascii');

-- ============================================================
-- SKILLS – procedural skill library (Python owner)
-- ============================================================
CREATE TABLE IF NOT EXISTS skills (
    skill_id      TEXT NOT NULL PRIMARY KEY,
    name          TEXT NOT NULL,
    version       INTEGER NOT NULL DEFAULT 1,
    docstring     TEXT NOT NULL,   -- used as embedding target
    code_body     TEXT NOT NULL,
    language      TEXT NOT NULL DEFAULT 'python',
    success_count INTEGER NOT NULL DEFAULT 0,
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_skills_name ON skills(name, version DESC);
CREATE VIRTUAL TABLE IF NOT EXISTS skills_fts
    USING fts5(skill_id UNINDEXED, name, docstring, tokenize='porter ascii');

-- ============================================================
-- SLEEP LOG – nightly consolidation runs (Python owner)
-- ============================================================
CREATE TABLE IF NOT EXISTS sleep_log (
    run_id              TEXT NOT NULL PRIMARY KEY,
    started_at          INTEGER NOT NULL,
    finished_at         INTEGER,
    phase               TEXT NOT NULL,  -- nrem_replay|transitive_closure|rem_abstract|shy_downscale
    nodes_processed     INTEGER NOT NULL DEFAULT 0,
    edges_strengthened  INTEGER NOT NULL DEFAULT 0,
    edges_pruned        INTEGER NOT NULL DEFAULT 0,
    lessons_added       INTEGER NOT NULL DEFAULT 0,
    skills_added        INTEGER NOT NULL DEFAULT 0,
    notes               TEXT
);

-- ============================================================
-- DECISIONS – Drex audit log (Python owner)
-- ============================================================
CREATE TABLE IF NOT EXISTS decisions (
    decision_id    TEXT NOT NULL PRIMARY KEY,  -- Drex request_id
    state_summary  TEXT NOT NULL,
    questions_json TEXT NOT NULL,
    answers_json   TEXT NOT NULL,
    confidence     REAL,
    latency_ms     REAL,
    model          TEXT NOT NULL DEFAULT 'drex-v1.5',
    created_at     INTEGER NOT NULL
);
