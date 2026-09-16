---
name: cobol-discovery
description: Phase 0 of COBOL-to-C# migration. Inventories a COBOL source tree — file count, LOC, PROGRAM-ID, CALL graph seeds. Deterministic, no LLM judgment. Triggers on starting a new migration run against a COBOL repo.
---

# COBOL Discovery

Purpose: build the initial file inventory before any analysis runs.

## Input
Path to COBOL source root (e.g. `cobol-accounting-system/`).

## Steps (deterministic, no LLM)
1. Glob `**/*.cob` `**/*.cbl` `**/*.cpy` under the root.
2. Per file: compute sha256, count LOC, grep first `PROGRAM-ID.` line.
3. Insert one row per file into `cobol_files` (see `migration-state/schema.sql`).
4. Create one `migration_runs` row (status=RUNNING, source_repo=path).

## Output
`cobol_files` rows populated for this `run_id`. No analysis yet — that's Phase 1 (`cobol-structural-analysis`).

## Exit criteria
Every `.cob`/`.cbl` file under the root has exactly one `cobol_files` row. Zero files found = hard fail, do not proceed to Phase 1.

## Feeds
`cobol-structural-analysis` (reads `cobol_files` for this run_id).
