-- Migration pipeline state schema (SQLite, demo scale)
-- Source design: design/12-data-modeling.md
-- All tables scoped by run_id so concurrent/historical runs never collide.

PRAGMA foreign_keys = ON;

CREATE TABLE migration_runs (
    run_id          TEXT PRIMARY KEY,          -- ULID
    started_at      TEXT NOT NULL,             -- ISO8601, stamped by caller (no Date.now in-tool)
    finished_at     TEXT,
    status          TEXT NOT NULL DEFAULT 'RUNNING', -- RUNNING|PASSED|FAILED|ABORTED
    target_lang     TEXT NOT NULL DEFAULT 'csharp',
    source_repo     TEXT NOT NULL,             -- path to COBOL source
    notes           TEXT
);

CREATE TABLE cobol_files (
    file_id         TEXT PRIMARY KEY,          -- ULID
    run_id          TEXT NOT NULL REFERENCES migration_runs(run_id),
    path            TEXT NOT NULL,             -- e.g. cobol-accounting-system/main.cob
    program_id      TEXT,                      -- PROGRAM-ID from source
    loc             INTEGER,
    sha256          TEXT NOT NULL
);

CREATE TABLE cobol_analyses (
    analysis_id     TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES migration_runs(run_id),
    file_id         TEXT NOT NULL REFERENCES cobol_files(file_id),
    divisions_json  TEXT NOT NULL,
    variables_json  TEXT NOT NULL,
    paragraphs_json TEXT NOT NULL,
    complexity_tier TEXT NOT NULL,             -- LOW|MEDIUM|HIGH
    created_at      TEXT NOT NULL
);

CREATE TABLE business_logic_extracts (
    extract_id      TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES migration_runs(run_id),
    file_id         TEXT NOT NULL REFERENCES cobol_files(file_id),
    user_stories_json TEXT NOT NULL,
    business_rules_json TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE dependency_edges (
    edge_id         TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES migration_runs(run_id),
    from_file_id    TEXT NOT NULL REFERENCES cobol_files(file_id),
    to_file_id      TEXT NOT NULL REFERENCES cobol_files(file_id),
    edge_type       TEXT NOT NULL              -- CALL|COPY|PERFORM
);

CREATE TABLE generated_files (
    gen_id          TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES migration_runs(run_id),
    source_file_id  TEXT NOT NULL REFERENCES cobol_files(file_id),
    target_path     TEXT NOT NULL,             -- e.g. src/Domain/Operations.cs
    sha256          TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE test_results (
    test_run_id     TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES migration_runs(run_id),
    gen_id          TEXT NOT NULL REFERENCES generated_files(gen_id),
    line_coverage   REAL,
    branch_coverage REAL,
    passed          INTEGER NOT NULL,          -- 0|1
    report_path     TEXT,
    created_at      TEXT NOT NULL
);

CREATE TABLE parity_verdicts (
    verdict_id      TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES migration_runs(run_id),
    fixture_name    TEXT NOT NULL,
    cobol_output    TEXT NOT NULL,
    csharp_output   TEXT NOT NULL,
    match           INTEGER NOT NULL,          -- 0|1
    divergence_class TEXT,                     -- REAL_BUG|INTENTIONAL_CHANGE|REPRESENTATION_DIFFERENCE|NULL
    created_at      TEXT NOT NULL
);

CREATE TABLE cost_logs (
    log_id          TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES migration_runs(run_id),
    phase           TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    input_tokens    INTEGER NOT NULL,
    output_tokens   INTEGER NOT NULL,
    cost_usd        REAL NOT NULL,
    latency_ms      INTEGER,
    created_at      TEXT NOT NULL
);

CREATE INDEX idx_files_run ON cobol_files(run_id);
CREATE INDEX idx_analyses_run ON cobol_analyses(run_id);
CREATE INDEX idx_edges_run ON dependency_edges(run_id);
CREATE INDEX idx_generated_run ON generated_files(run_id);
CREATE INDEX idx_parity_run ON parity_verdicts(run_id);
CREATE INDEX idx_cost_run ON cost_logs(run_id);
