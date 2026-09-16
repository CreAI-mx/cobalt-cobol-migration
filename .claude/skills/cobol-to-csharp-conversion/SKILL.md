---
name: cobol-to-csharp-conversion
description: Phase 4 of COBOL-to-C# migration. Generates target C# code from COBOL analysis + business logic + dependency order. Agentic (LLM) — invoke Claude Code headless per file, fresh session, no shared chat history. Triggers after cobol-dependency-mapping, in leaf-first order.
---

# COBOL to C# Conversion

Purpose: produce idiomatic, compiling C# that preserves COBOL semantics exactly — not a transliteration.

## Target shape: Clean Architecture, NOT 1:1 (user decision, supersedes design/04's original "classes mapped 1:1" exit criterion)
- Layered structure: `{Sln}.Domain` (entities/value objects from copybooks), `{Sln}.Application/UseCases/{BehaviorName}/` (one handler + port interface per COBOL program, named from extracted BEHAVIOR — Phase 2 output — not from the filename), `{Sln}.Infrastructure` (port adapters), `{Sln}.Cli` (composition root).
- SOLID enforced: single responsibility per handler, dependencies point inward (dependency rule), ports/interfaces at boundaries, no God classes.
- Design patterns where warranted by the COBOL's actual behavior (repository for file I/O, strategy for EVALUATE dispatch) — never pattern-for-pattern's-sake.
- Complexity limits: methods <50 lines, no nesting >4 deep — spaghetti COBOL gets RESTRUCTURED into clean code, while the Parity Gate (Phase 6) proves behavior stayed identical. Structure changes; behavior must not.
- Output is git-versioned per run: generated code committed under the run's ULID so every migration run is diffable and revertible.

## Input
Per file, in leaf-first order from `dependency_edges`: `cobol_analyses` row + `business_logic_extracts` row + target-file conventions.

## Mandatory semantic rules (non-negotiable, checked in Phase 6)
- **Session-persistent state across CALLs** (verified present in this demo repo — the single most important rule below): COBOL `WORKING-STORAGE` in a called subprogram (e.g. `DataProgram.STORAGE-BALANCE` in `data.cob:6`) initializes once per process and persists across every subsequent `CALL` to that program within the same run — it is NOT re-initialized per call. A C# port that instantiates a fresh object per call (the natural OO instinct) silently resets state on every operation. The generated C# MUST use a singleton/static-lifetime instance (or equivalent DI scope) for any class ported from a COBOL subprogram whose WORKING-STORAGE outlives a single CALL. Verify: a fixture that calls CREDIT then DEBIT then TOTAL in one session must show the C# balance reflecting both prior operations, not a reset to the initial VALUE.
- `COMP-3` / `PACKED-DECIMAL` → C# `decimal`. NEVER `float`/`double`. This is the single most-cited cause of migrations that "compile perfectly and corrupt the ledger" in COBOL migrations generally — but confirm it actually applies before spending effort defending against it: this demo repo's fields (`PIC 9(6)V99` in `data.cob`/`operations.cob`) are plain unsigned zoned-decimal DISPLAY, not COMP-3. The real gotcha present here is the implied decimal point (`V99` — no physical decimal character in storage) plus the unsigned field (no `S` — `SUBTRACT` at `operations.cob:33` is only safe because of the `>=` guard at line 32, not a sign check). Don't assume COMP-3 rules apply without checking the PIC clause first.
- `REDEFINES` → requires explicit human-reviewed mapping decision (child table / wide nullable table / raw blob). Never auto-generate silently.
- EBCDIC-dependent sort/collation logic → flag for manual review; ASCII sort order differs (lowercase/uppercase/digit ordering flips) and breaks control-break logic silently, with no compile error.

## Invocation pattern
Headless Claude Code per file: `claude -p "<conversion prompt with analysis+business-logic context>" --output-format json --allowedTools "Read,Write" --add-dir <target-project-dir>`. Fresh session per file — state flows through `generated_files` rows, not chat continuity.

## Output language (standing rule, repeated across every generation skill on purpose)
English for ALL generated artifacts: C# identifiers, code comments, CONVERSION-NOTES.md
entries, commit messages for the git-versioned output. Dense, factual, no filler.
Never mirror the COBOL source's comment language into the generated C#.

## Submodule documentation (same turn as the handler)
Callers: `backend/llm.py` `_CONVERT_PROMPT_TEMPLATE` (this section is mirrored there) and
`backend/routers/pipeline.py` `_run_phase4`. No new table — the README is another
`generated_files` path next to the handler. User asked for per-module/submodule docs so
agents jump to one MD without reading the whole tree.

Write `UseCases/{Behavior}/README.md` next to the handler. Audience: coding agents.
Ontological YAML frontmatter (`id: uc.{Name}`, `type: UseCase`, `part_of`, `implements`,
`depends_on`, `invariants`, `graph: docs/ontology/GRAPH.md`) then ≤60 lines:
COBOL origin, public types (names only), invariants that must not break, up-links
to GRAPH.md. Do **not** write SCHEMA.md / GRAPH.md / root README in this turn.

## Output
`generated_files` row: `target_path`, `sha256`.

## Exit criteria
File compiles (`dotnet build`) before this phase is marked done for that file. A file that doesn't compile is NOT handed to Phase 5 — loop back within this phase, bounded retries (see design/08-bug-resolution.md).

## Feeds
`csharp-test-generation` (parallel), `parity-validation` (after both 4 and 5 done for a unit).
