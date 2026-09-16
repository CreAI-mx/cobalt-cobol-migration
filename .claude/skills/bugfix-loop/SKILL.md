---
name: bugfix-loop
description: Triggered when parity-validation reports a mismatch. Triages divergence, fixes the root cause (or the rulebook, if the same class of bug recurs), re-runs the full regression, never patches blind. Triggers on any parity_verdicts row with match=0.
---

# Bugfix Loop

Purpose: close a parity gap without introducing a new one, and without silently repeating the same mistake file after file.

## Input
`parity_verdicts` row with `match=0`.

## Triage (deterministic detection, LLM classification, human authority on ambiguity)
1. `REAL_BUG` — generated C# diverges from documented COBOL behavior. Fix required.
2. `INTENTIONAL_IMPROVEMENT` — someone deliberately wants different behavior. Requires human sign-off, never auto-applied.
3. `LEGACY_QUIRK_TO_PRESERVE` — COBOL behavior is "wrong" by modern standards but must be preserved for compatibility (e.g. a rounding quirk downstream systems depend on). Requires human sign-off on first occurrence; later occurrences of the same quirk auto-apply the prior ruling.
4. `TEST_ORACLE_DEFECT` — the fixture itself is wrong, not the code.

## The recurrence rule (non-negotiable)
If the same class of divergence appears in 3+ files, OR any divergence type recurs a 2nd time after a fix — STOP patching files one by one. Generalize the fix into the conversion rulebook (`cobol-to-csharp-conversion` skill instructions), version that change, re-run a deterministic batch-fix across all affected files, and add a regression fixture so it can never silently reappear. "Fix the process, not the code."

## Steps
1. Classify (see above).
2. If REAL_BUG or ruled quirk: apply fix, re-run full regression suite (Phase 5 + Phase 6), not just the failing fixture.
3. Append to `migration-state/rulebook.md` if this triggers the recurrence rule.
4. Log every decision to an append-only ledger — no silent overwrite of a prior verdict.

## Output
Updated `generated_files`/`parity_verdicts`, and `migration-state/rulebook.md` on recurrence.

## Feeds
Back to `parity-validation` (re-gate) or human approval gate (if resolved).
