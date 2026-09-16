---
name: csharp-test-generation
description: Phase 5 of COBOL-to-C# migration (parallel with Phase 4). Generates xUnit tests for migrated C# code, driven by extracted business rules and a COMP-3/decimal edge-case matrix. Agentic for test authoring, deterministic for coverage gating. Triggers per generated file.
---

# C# Test Generation

Purpose: every migrated file ships with tests that would catch a semantic regression, not just a compile check.

## Input
`generated_files` row + `business_logic_extracts.business_rules_json` for the same source file.

## Steps
1. One test per extracted business rule (traceable title, e.g. `Debit_RejectsWhenAmountExceedsBalance`).
2. Mandatory decimal edge-case matrix for any COMP-3-derived field: zero, one-cent, max-domain value, boundary at `>=`/`>` comparisons, truncation-not-rounding behavior, scale-overflow.
3. Mock cross-file dependencies (e.g. `DataProgram` calls) with Moq — do not require the full call chain compiled to unit-test one class.
4. Run `dotnet test --collect:"XPlat Code Coverage"`.

## Gate thresholds
90% line coverage, 85% branch coverage on the migrated file; 80% rolling floor project-wide. Below threshold = fail this phase, do not proceed to Phase 6 for this file.

## Output language (standing rule, repeated across every generation skill on purpose)
English for test names, assertions, and comments — dense, factual, no filler.

## Output
`test_results` row: `line_coverage`, `branch_coverage`, `passed`, `report_path`.

## Feeds
`parity-validation` (only files passing this gate proceed).
