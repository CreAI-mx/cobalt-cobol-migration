# 12 — Data Modeling & Persistence

Scope: persistence layer for the agentic COBOL→C# migration pipeline. Demo target:
`/home/frg/creai/cobol/cobol-accounting-system` (3 COBOL files: `main.cob`, `operations.cob`,
`data.cob`). Design must not assume a rewrite for scale-up — it must state the exact
migration path from demo-scale to enterprise-scale.

## 1. Storage engine decision

**SQLite for the demo, Postgres for production, explicit migration path between them.**

| Axis | SQLite | Postgres |
|---|---|---|
| Concurrency | single-writer, file-locked; fine for one pipeline run at a time | MVCC, multi-agent concurrent writers |
| Setup | zero-install, single file, matches Azure-Samples `agentic-legacy-modernization` reference pattern | needs a server/container, connection pooling |
| Scale | fine to low hundreds of thousands of rows / dozens of files | required past ~1k COBOL files, multi-tenant, multi-run concurrency |
| JSON support | `json1` extension, adequate for semi-structured AST/analysis blobs | native `jsonb`, indexable, required at scale |
| Ops | file backup = copy | needs migrations tooling, backup/replica strategy |

Decision: **SQLite** for this repo (3 files, single operator, single pipeline run at a
time — the concurrency ceiling of SQLite is irrelevant here). Schema is written in
ANSI-ish SQL that runs unmodified on both engines except for three known deltas (see
§6), so the same schema file is the Postgres schema on day one of a production port.

Rationale against defaulting to Postgres now: YAGNI — provisioning a server for 3 files
and one operator is pure overhead with no return until either (a) multiple pipeline runs
must execute concurrently, or (b) the corpus crosses roughly 500–1000 files where
SQLite's single-writer lock starts serializing agent write bursts (dependency-graph
construction, parallel per-file analysis writes).

### 1.1 Graph store (Neo4j): deferred, not adopted

The dependency graph at this repo's scale is **3 nodes, ≤3 edges** (`main.cob` CALLs
`operations.cob`, both COPY/reference `data.cob`'s working-storage layout). A dedicated
graph database is unjustified: no query in this pipeline needs multi-hop graph traversal
that a recursive CTE over an adjacency-list table can't answer at this N. Standing up
Neo4j for a 3-node graph is accidental complexity — an infra dependency, a second query
language, a second backup story — for zero traversal-performance benefit.

**Adopt Neo4j only when**: the corpus reaches the scale where dependency chains exceed
~4-5 hops routinely (real COBOL portfolios: batch job chains, CICS transaction maps,
copybook fan-in across hundreds of programs) **and** the pipeline needs graph-native
queries (shortest migration path, blast-radius of a shared copybook change, cyclic
CALL detection at scale) that become awkward or slow as recursive SQL. Until then, the
`dependency_edges` table (§4) plus recursive CTEs is sufficient and keeps the stack at
one engine. Design the DAO layer (§7) behind a `GraphRepository` interface so that
swapping the SQL-backed implementation for a Neo4j-backed one later is a single
adapter, not a pipeline rewrite.

## 2. Entity overview

```
migration_runs (1) ──< cobol_files (1) ──< cobol_analyses (1)
                    │                  ├──< business_logic_extracts (N)
                    │                  └──< generated_files (N) ──< test_results (N)
                    ├──< dependency_edges (N, self-referential over cobol_files)
                    ├──< parity_verdicts (N)  [FK → generated_files, cobol_files]
                    └──< cost_logs (N)
```

One `migration_run` = one end-to-end pipeline execution over the target repo. Re-running
the pipeline (e.g. after a prompt change) creates a new `migration_runs` row rather than
mutating history — every artifact is versioned by `run_id`, giving free A/B comparison
between pipeline iterations without extra tables.

## 3. Schema — core pipeline state

```sql
-- One row per pipeline execution.
CREATE TABLE migration_runs (
    run_id          TEXT PRIMARY KEY,           -- ULID, sortable by creation time
    source_repo_path TEXT NOT NULL,
    target_language TEXT NOT NULL DEFAULT 'csharp',
    pipeline_version TEXT NOT NULL,             -- git sha / semver of the agent pipeline
    status          TEXT NOT NULL CHECK (status IN
                        ('pending','analyzing','extracting','generating',
                         'testing','parity_check','completed','failed','aborted')),
    started_at      TEXT NOT NULL,              -- ISO-8601 UTC
    finished_at     TEXT,
    error_summary   TEXT,                       -- non-null only if status='failed'
    config_json     TEXT NOT NULL               -- frozen copy of run config (model ids,
                                                 -- thresholds, feature flags) for repro
);

-- One row per COBOL source file discovered under source_repo_path, per run.
CREATE TABLE cobol_files (
    file_id         TEXT PRIMARY KEY,           -- ULID
    run_id          TEXT NOT NULL REFERENCES migration_runs(run_id),
    relative_path   TEXT NOT NULL,              -- e.g. 'main.cob'
    content_sha256  TEXT NOT NULL,              -- detects source drift across runs
    program_id      TEXT,                       -- PROGRAM-ID. value, nullable pre-parse
    loc             INTEGER,
    UNIQUE (run_id, relative_path)
);

-- One row per completed static-analysis pass on a cobol_files row.
-- 1:1 with cobol_files but modeled as its own table (not inline columns) because
-- analysis is produced by a distinct agent step and may be retried independently.
CREATE TABLE cobol_analyses (
    analysis_id     TEXT PRIMARY KEY,
    file_id         TEXT NOT NULL UNIQUE REFERENCES cobol_files(file_id),
    divisions_json  TEXT NOT NULL,   -- {IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE}
    data_items_json TEXT NOT NULL,   -- working-storage layout: name, PIC clause,
                                     -- level, redefines, occurs, computed C# type
    paragraphs_json TEXT NOT NULL,   -- paragraph name -> {called_by, calls, loc_range}
    called_programs_json TEXT,       -- external CALL 'X' targets, pre-graph-resolution
    complexity_score REAL,           -- e.g. cyclomatic proxy over PERFORM/GO TO/IF nesting
    model_id        TEXT NOT NULL,   -- which LLM produced this analysis
    prompt_version  TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

-- Extracted business-rule statements, N per file (a file yields many rules).
CREATE TABLE business_logic_extracts (
    extract_id      TEXT PRIMARY KEY,
    file_id         TEXT NOT NULL REFERENCES cobol_files(file_id),
    paragraph_name  TEXT,                       -- source PROCEDURE DIVISION paragraph
    rule_text       TEXT NOT NULL,               -- natural-language rule statement
    source_lines    TEXT NOT NULL,               -- 'start-end' line range in original file
    category        TEXT CHECK (category IN
                        ('validation','calculation','control_flow','io','error_handling')),
    confidence      REAL,                        -- extractor's self-reported confidence
    model_id        TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
```

## 4. Schema — dependency graph

Adjacency-list table, not a separate node/edge pair of tables — `cobol_files` already
is the node table, so only edges need modeling.

```sql
CREATE TABLE dependency_edges (
    edge_id         TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES migration_runs(run_id),
    from_file_id    TEXT NOT NULL REFERENCES cobol_files(file_id),
    to_file_id      TEXT NOT NULL REFERENCES cobol_files(file_id),
    edge_type       TEXT NOT NULL CHECK (edge_type IN ('CALL','COPY','DATA_SHARE')),
    -- CALL: from_file issues CALL 'to_file' PROGRAM-ID
    -- COPY: from_file has COPY to_file (copybook inclusion)
    -- DATA_SHARE: both reference the same working-storage layout without COPY (heuristic)
    detail          TEXT,             -- e.g. the literal CALL statement text
    UNIQUE (run_id, from_file_id, to_file_id, edge_type)
);
CREATE INDEX idx_dep_edges_from ON dependency_edges(from_file_id);
CREATE INDEX idx_dep_edges_to   ON dependency_edges(to_file_id);
```

For this repo: expect exactly the edges `main→operations (CALL)`, `main→data (COPY or
DATA_SHARE)`, `operations→data (COPY or DATA_SHARE)` — verify against actual COPY
statements in `data.cob`/`operations.cob` during analysis rather than assuming.

Topological ordering for generation sequencing (`data.cob` before `operations.cob`
before `main.cob`) is a plain recursive CTE over this table — no graph engine needed:

```sql
WITH RECURSIVE topo(file_id, depth) AS (
  SELECT file_id, 0 FROM cobol_files
  WHERE run_id = :run_id
    AND file_id NOT IN (SELECT from_file_id FROM dependency_edges WHERE run_id = :run_id)
  UNION ALL
  SELECT e.from_file_id, t.depth + 1
  FROM dependency_edges e JOIN topo t ON e.to_file_id = t.file_id
  WHERE e.run_id = :run_id
)
SELECT file_id, MAX(depth) AS order_rank FROM topo GROUP BY file_id ORDER BY order_rank;
```

## 5. Schema — generated artifacts, tests, parity, cost

```sql
-- Generated C# source files. Many-to-one with cobol_files: a COBOL program may expand
-- into multiple C# files (class + interface + DTO); many_to_one because it also stores
-- solution/project-level files that map to no single source file (Program.cs, .csproj).
CREATE TABLE generated_files (
    gen_file_id     TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES migration_runs(run_id),
    source_file_id  TEXT REFERENCES cobol_files(file_id),   -- NULL for solution-level files
    relative_path   TEXT NOT NULL,               -- e.g. 'src/Operations.cs'
    file_kind       TEXT NOT NULL CHECK (file_kind IN
                        ('class','interface','dto','test','project','solution','config')),
    content_sha256  TEXT NOT NULL,
    generation_attempt INTEGER NOT NULL DEFAULT 1,  -- increments on regen-after-failure
    model_id        TEXT NOT NULL,
    prompt_version  TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    UNIQUE (run_id, relative_path, generation_attempt)
);

-- Test execution results against generated_files (unit tests the pipeline wrote/ran).
CREATE TABLE test_results (
    test_result_id  TEXT PRIMARY KEY,
    gen_file_id     TEXT NOT NULL REFERENCES generated_files(gen_file_id),
    test_framework  TEXT NOT NULL DEFAULT 'xunit',
    test_name       TEXT NOT NULL,
    outcome         TEXT NOT NULL CHECK (outcome IN ('pass','fail','error','skipped')),
    duration_ms     INTEGER,
    failure_message TEXT,
    executed_at     TEXT NOT NULL
);

-- Parity gate verdicts: does generated C# behavior match original COBOL behavior for
-- a given input scenario. This is the pipeline's release gate, kept as its own table
-- (not folded into test_results) because a verdict aggregates over one-or-more
-- test_results plus a semantic diff score, and outlives any single test run.
CREATE TABLE parity_verdicts (
    verdict_id      TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES migration_runs(run_id),
    cobol_file_id   TEXT NOT NULL REFERENCES cobol_files(file_id),
    gen_file_id     TEXT NOT NULL REFERENCES generated_files(gen_file_id),
    scenario_name   TEXT NOT NULL,               -- e.g. 'deposit-then-withdraw-overdraft'
    cobol_output    TEXT,                        -- captured stdout/output record from GnuCOBOL run
    csharp_output   TEXT,                        -- captured output from the C# equivalent
    diff_summary    TEXT,                        -- structured diff, empty if match
    verdict         TEXT NOT NULL CHECK (verdict IN ('match','mismatch','error','not_run')),
    reviewed_by     TEXT,                        -- 'auto' or human reviewer id, for gate sign-off
    created_at      TEXT NOT NULL
);

-- Token/cost accounting per agent invocation, for budget tracking and per-run cost reports.
CREATE TABLE cost_logs (
    cost_log_id     TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES migration_runs(run_id),
    pipeline_stage  TEXT NOT NULL,               -- 'analysis','extraction','generation','parity'
    file_id         TEXT REFERENCES cobol_files(file_id),  -- NULL for run-level calls
    model_id        TEXT NOT NULL,
    input_tokens    INTEGER NOT NULL,
    output_tokens   INTEGER NOT NULL,
    cached_input_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd        REAL NOT NULL,
    called_at       TEXT NOT NULL
);
CREATE INDEX idx_cost_logs_run ON cost_logs(run_id);
```

Roll-up cost per run:

```sql
SELECT run_id, pipeline_stage, SUM(cost_usd) AS stage_cost,
       SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok
FROM cost_logs GROUP BY run_id, pipeline_stage;
```

## 6. SQLite → Postgres migration path

Schema portability deltas, kept minimal by design choice:

1. **IDs**: use ULIDs generated in application code (`TEXT PRIMARY KEY`), not
   `AUTOINCREMENT`/`SERIAL`. Identical on both engines, no rewrite.
2. **JSON columns**: `TEXT` holding JSON strings on SQLite (queried via `json1`
   functions where needed) become `JSONB` on Postgres with a one-line `ALTER COLUMN
   ... TYPE jsonb USING col::jsonb`. Application code should serialize/deserialize at
   the DAO boundary either way, so no call-site changes.
3. **Timestamps**: store as ISO-8601 `TEXT` on SQLite; becomes `TIMESTAMPTZ` on
   Postgres via `ALTER COLUMN ... TYPE timestamptz USING col::timestamptz`.

Migration mechanics: `sqlite3 demo.db .dump` → strip SQLite-specific pragmas → run
against Postgres → apply the three `ALTER COLUMN` deltas → re-point the DAO layer's
connection string. No table redesign, no data remodeling. Recommended trigger points:
concurrent multi-run execution needed, or corpus > ~500 files.

## 7. DAO / repository layer

One repository interface per aggregate, SQL-engine-agnostic (parameterized queries
only, no engine-specific syntax in application code):

- `MigrationRunRepository`
- `CobolFileRepository`
- `AnalysisRepository`
- `BusinessLogicRepository`
- `GraphRepository` — backed by `dependency_edges` today; swappable for a Neo4j
  adapter without touching callers (see §1.1)
- `GeneratedFileRepository`
- `TestResultRepository`
- `ParityRepository`
- `CostLogRepository`

Each repository takes `run_id` as a mandatory filter parameter (never a global table
scan) so that multiple historical runs coexist in one file/DB without cross-run leakage.

## 8. Indexing summary

Beyond the two explicit indexes in §4 and cost_logs:

```sql
CREATE INDEX idx_cobol_files_run ON cobol_files(run_id);
CREATE INDEX idx_analyses_file ON cobol_analyses(file_id);
CREATE INDEX idx_extracts_file ON business_logic_extracts(file_id);
CREATE INDEX idx_genfiles_run ON generated_files(run_id);
CREATE INDEX idx_genfiles_source ON generated_files(source_file_id);
CREATE INDEX idx_testresults_genfile ON test_results(gen_file_id);
CREATE INDEX idx_parity_run ON parity_verdicts(run_id);
```

At this repo's scale (3 files) these indexes carry no measurable performance benefit;
they are specified now because the DDL is the same file that ports to Postgres, and
retrofitting indexes later is a second migration nobody should have to write.

## 9. Non-goals / explicitly deferred

- **Neo4j** — see §1.1. Revisit at portfolio scale with genuine multi-hop query needs.
- **Vector store for RAG over COBOL semantics** — out of scope for this doc; if the
  pipeline later embeds COBOL snippets for retrieval-augmented rule extraction, that
  is a separate `embeddings` table (or dedicated vector DB) keyed by `file_id`, added
  without touching this schema.
- **Multi-tenant row-level security** — irrelevant at single-operator demo scale;
  becomes a Postgres RLS policy problem at production scale, not a schema problem.
- **Write-ahead audit log / event sourcing** — `migration_runs` + per-table
  `created_at` timestamps give sufficient provenance at this scale; full event
  sourcing is unjustified complexity for a 3-file demo.
