---
name: cobol-structural-analysis
description: Phase 1 of COBOL-to-C# migration. Parses COBOL structure — DIVISIONs, WORKING-STORAGE/LINKAGE variables (PIC/COMP clauses), paragraphs. Prefers a real parser (ProLeap) over regex; complexity scoring decides LLM reasoning effort downstream. Triggers after cobol-discovery completes for a run.
---

# COBOL Structural Analysis

Purpose: turn raw COBOL text into a typed structural record — the ground truth every later phase trusts.

## Input
`cobol_files` rows for this `run_id` (from `cobol-discovery`).

## Steps
1. Per file, parse (ProLeap COBOL Parser preferred; regex fallback only if parser unavailable — flag fallback explicitly in output, never silently).
2. Extract: DIVISIONs present, WORKING-STORAGE + LINKAGE variables with PIC/COMP/REDEFINES clauses, paragraph names + call targets (CALL/PERFORM/COPY).
3. Score complexity: LOW (no SQL/CICS/REDEFINES) / MEDIUM (some) / HIGH (heavy REDEFINES, OCCURS DEPENDING ON, EBCDIC-sensitive sort logic).
4. Flag every `COMP-3`/`PACKED-DECIMAL` field explicitly — these MUST map to C# `decimal`, never `float`/`double`, in Phase 4.
5. Flag every `REDEFINES` explicitly — these need human decision in Phase 4, never silent auto-mapping.
6. Write one `cobol_analyses` row per file.

## Output
`cobol_analyses` row: `divisions_json`, `variables_json`, `paragraphs_json`, `complexity_tier`.

## Exit criteria
Every `cobol_files` row for this run has exactly one `cobol_analyses` row. Any COMP-3 or REDEFINES field must appear tagged in `variables_json` — untagged = fail this phase.

## Feeds
`cobol-business-logic-extraction`, `cobol-dependency-mapping` (both run in parallel off this output).
