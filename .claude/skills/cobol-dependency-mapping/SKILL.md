---
name: cobol-dependency-mapping
description: Phase 3 of COBOL-to-C# migration. Builds the CALL/COPY/PERFORM dependency graph across all COBOL files in a run. Deterministic — pure graph construction from already-parsed data, no LLM. Triggers after cobol-structural-analysis for all files in a run.
---

# COBOL Dependency Mapping

Purpose: know the conversion order before converting anything — leaf programs first, entry points last.

## Input
`cobol_analyses.paragraphs_json` for every file in this `run_id` (CALL targets already extracted in Phase 1).

## Steps (deterministic, no LLM)
1. For each file, resolve CALL/COPY targets against `cobol_files.program_id` in the same run.
2. Insert `dependency_edges` rows (`from_file_id`, `to_file_id`, `edge_type`).
3. Compute topological order via recursive CTE (no graph DB needed at demo scale — see design/12-data-modeling.md). Cyclic CALL = flag loudly, do not silently pick an order.

## Output
`dependency_edges` rows + a derived conversion order (leaf-first).

## Exit criteria
Every CALL/COPY target resolved to an existing `cobol_files` row, or explicitly flagged as external/unresolved (never silently dropped).

## Feeds
`cobol-to-csharp-conversion` (determines which files convert first).
