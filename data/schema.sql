-- Reference relational schema for the take-home. SQLite-flavoured; portable to
-- Azure SQL / PostgreSQL with minimal changes (types, autoincrement, UTC now()).
-- You may adapt column names or add indexes — this is a starting point, not a spec.

CREATE TABLE IF NOT EXISTS policy (
    policy_id   TEXT PRIMARY KEY,
    retailer    TEXT NOT NULL,              -- 'northstar' | 'cedar'
    category    TEXT NOT NULL,              -- returns | damaged_item | shipping
    text        TEXT NOT NULL
);

-- Retrieval is always scoped by retailer; index supports that access pattern.
CREATE INDEX IF NOT EXISTS ix_policy_retailer ON policy (retailer);

CREATE TABLE IF NOT EXISTS triage_log (
    request_id      TEXT PRIMARY KEY,       -- unique per request
    ticket_id       TEXT NOT NULL,
    retailer        TEXT NOT NULL,
    category        TEXT,
    decision        TEXT NOT NULL,          -- policy_supported | needs_information | human_review
    policy_ids      TEXT,                   -- e.g. JSON array or comma-separated cited IDs
    model_provider  TEXT,
    fallback        INTEGER NOT NULL DEFAULT 0,   -- 0/1
    latency_ms      INTEGER,
    created_at      TEXT NOT NULL           -- ISO-8601 UTC
);

CREATE INDEX IF NOT EXISTS ix_triage_log_created ON triage_log (created_at);
