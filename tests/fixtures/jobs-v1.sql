
CREATE TABLE jobs (
    job_id TEXT PRIMARY KEY NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','rendering','merging','done','failed')),
    template_name TEXT NOT NULL,
    record_count INTEGER NOT NULL CHECK(record_count > 0),
    copies INTEGER NOT NULL CHECK(copies > 0),
    batch_count INTEGER NOT NULL CHECK(batch_count > 0),
    created_at INTEGER NOT NULL,
    started_at INTEGER,
    finished_at INTEGER,
    expires_at INTEGER,
    final_name TEXT CHECK(final_name IS NULL OR final_name = job_id || '.pdf'),
    publication_intent_at INTEGER,
    error_code TEXT,
    error_message TEXT,
    CHECK ((status IN ('done','failed') AND finished_at IS NOT NULL AND expires_at IS NOT NULL)
        OR (status NOT IN ('done','failed') AND finished_at IS NULL)),
    CHECK (status != 'done' OR (final_name IS NOT NULL AND publication_intent_at IS NOT NULL
        AND error_code IS NULL)),
    CHECK (status != 'failed' OR error_code IS NOT NULL)
);
CREATE INDEX jobs_created ON jobs(created_at DESC);
CREATE INDEX jobs_expiry ON jobs(expires_at) WHERE expires_at IS NOT NULL;
PRAGMA user_version = 1;
