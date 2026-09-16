---
name: parity-validation
description: Phase 6 of COBOL-to-C# migration. Deterministic gate — compiles and runs both the original COBOL (via GnuCOBOL) and the generated C# against identical input fixtures, diffs output exactly. No LLM in the pass/fail decision. Triggers after test-generation passes for all files in a unit.
---

# Parity Validation Gate

Purpose: prove the migrated system behaves identically to the original, not just "looks right."

## Prerequisite (hard blocker)
`cobc` (GnuCOBOL) and `dotnet` SDK must both be installed and on PATH. Verify with `which cobc dotnet` before running this phase — do not attempt partial validation without both compilers.

## Input
Original COBOL source + `generated_files` rows for the same unit, both build-ready.

## Steps (100% deterministic, zero LLM in the verdict)
1. `cobc -x <cobol files> -o cobol_oracle` — compile the original.
2. `dotnet build` the generated C# project.
3. Run both against identical stdin fixtures (view balance, credit, debit, insufficient-funds, invalid menu choice, multi-op session) — fresh process each run (COBOL resets in-memory balance to 1000.00 per launch, so must the C#).
4. Diff stdout byte-for-byte (after normalizing non-functional noise: timestamps, whitespace — never normalize away a numeric or decision difference).
5. Any mismatch → classify: `REAL_BUG` / `INTENTIONAL_CHANGE` / `REPRESENTATION_DIFFERENCE`. Ambiguous cases only escalate to an LLM judge (Locksmith-Loop style) — the LLM never overrides a clear numeric mismatch.

## Gate criteria
100% of fixtures must match exactly at this program size (3 files, no partial credit — see design/06-parity-testing.md). Larger codebases may relax to a coverage threshold; this demo does not.

## Output
`parity_verdicts` row per fixture.

## Feeds
`bugfix-loop` (on any mismatch) or human approval gate (on 100% pass).
