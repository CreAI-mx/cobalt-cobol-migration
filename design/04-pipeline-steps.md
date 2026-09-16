# 04 — Agentic Migration Pipeline: Phase Sequence

Scope: exact end-to-end phase sequence for agentic COBOL→C# migration. Demo target:
`/home/frg/creai/cobol/cobol-accounting-system/` — `main.cob` (menu, `CALL 'OperationsProgram'`)
→ `operations.cob` (`CALL 'DataProgram'` per op) → `data.cob` (in-memory `STORAGE-BALANCE`,
`READ`/`WRITE` linkage contract). No files, no DB — process-lifetime state only, lost on exit.

Order follows the brief exactly: discovery/inventory → structural analysis → business logic
extraction → dependency mapping → code conversion → test generation → parity validation →
human approval gate → merge. Each phase: **Entry criteria**, **Exit criteria**, **Artifacts**,
**Parallelizable?**. A "unit" is a group of programs sharing state/call topology that migrates
together; for this demo the whole 3-program chain is one unit (established in Phase 3).

---

## Phase 0 — Discovery / Inventory

**Entry**: repo path given, no assumptions about structure.
**Exit**: complete, checksummed file list; every `.cob`/`.cpy`/`.cbl`/JCL/proc file classified
(program / copybook / job control / build script); call graph skeleton (names only, unresolved).
**Artifacts**: `inventory.json` (path, hash, LOC, dialect guess), `call-graph-raw.json` (edges from
literal `CALL '...'` string scan, no static resolution yet).
**Parallel**: fully parallel across files (embarrassingly parallel file scan). Runs before
everything else — nothing downstream can start until the file set is known.

**Walkthrough**: scan finds 3 files, 100 LOC total, no copybooks, no JCL. Raw grep of `CALL '`
literals yields edges `MainProgram → OperationsProgram`, `OperationsProgram → DataProgram`. No
dynamic `CALL identifier` (all literals) → call graph is fully static, a strong simplifying fact
recorded now for Phase 3/4 to consume.

---

## Phase 1 — Structural Analysis

**Entry**: Phase 0 inventory complete.
**Exit**: per-program AST (IDENTIFICATION/DATA/PROCEDURE divisions parsed), WORKING-STORAGE and
LINKAGE SECTION field tables with PIC clauses resolved to concrete types + precision, paragraph/
section boundaries, control-flow graph per PROCEDURE DIVISION (PERFORM/EVALUATE/IF nesting).
**Artifacts**: `ast/<program>.json`, `fields/<program>.json` (name, PIC, VALUE, USAGE, LINKAGE
vs WORKING-STORAGE), `cfg/<program>.dot`.
**Parallel**: parallel per program (3 independent parses); must fully complete before Phase 2
(business logic extraction needs the CFG and field tables).

**Walkthrough**:
- `MainProgram`: fields `USER-CHOICE PIC 9`, `CONTINUE-FLAG PIC X(3)`; CFG = single `PERFORM
  UNTIL` loop containing one `EVALUATE` with 5 branches (1–4 + OTHER).
- `OperationsProgram`: `LINKAGE` param `PASSED-OPERATION PIC X(6)`; local `AMOUNT PIC 9(6)V99`,
  `FINAL-BALANCE PIC 9(6)V99 VALUE 1000.00` — flagged HIGH severity: this VALUE is dead/misleading
  since FINAL-BALANCE is always overwritten by `CALL 'DataProgram' USING 'READ', FINAL-BALANCE`
  before use; CFG = nested `IF/ELSE IF` chain (not EVALUATE) on TOTAL/CREDIT/DEBIT.
- `DataProgram`: `LINKAGE` params `PASSED-OPERATION PIC X(6)`, `BALANCE PIC 9(6)V99`;
  WORKING-STORAGE `STORAGE-BALANCE PIC 9(6)V99 VALUE 1000.00` — the *only* persistent field in the
  program. Its persistence model (static working-storage, alive only while the OS run unit
  lives, resident across `CALL`s within one run but not across process restarts) is flagged as an
  architectural fact whose full cross-program implications are resolved in Phase 3 (Dependency
  Mapping) and must carry into Phase 4 target design — a naive per-call translation could silently
  reset balance to 1000.00 on every call.

---

## Phase 2 — Business Logic Extraction

**Entry**: Phase 1 CFGs + field tables for each program; Phase 0's raw call graph (open question:
does `STORAGE-BALANCE` actually persist across separate menu selections, or only within one
`CALL`? — deferred to Phase 3, since it requires cross-program dataflow, not just one CFG).
**Exit**: language-agnostic behavior specification per program — pre/post-conditions, business
rules stated as assertions, edge cases enumerated, informal spec text plus machine-checkable
invariants where derivable from a single program's CFG; any rule that depends on cross-program
state topology is recorded as an **open item** for Phase 3 to close, not guessed at here.
**Artifacts**: `spec/<program>.md` + `spec/<program>.invariants.json`, `spec/open-items.json`.
**Parallel**: parallel per program (each CFG stands alone); independent of Phase 3, which only
needs Phase 2's per-program rules as input to reconcile across programs — the two phases do not
overlap in their working set (Phase 2 = one program at a time, Phase 3 = the edges between them).

**Walkthrough**:
- `MainProgram`: rule — loop displaying a 4-option menu until choice 4; invalid numeric or
  non-1–4 input displays "Invalid choice" and re-loops (no crash path); `ACCEPT USER-CHOICE` into
  `PIC 9` truncates/rejects non-digit input per COBOL runtime rules — edge case flagged for
  explicit handling in C# (`int.TryParse` won't behave identically; needs a defined mapping, e.g.
  non-numeric → OTHER branch).
- `OperationsProgram`: rule TOTAL — read balance, display it, no mutation. Rule CREDIT — prompt
  amount (`PIC 9(6)V99`, unsigned, 2 decimal places, max `999999.99`), read balance, unconditional
  add, write back, display new balance. Rule DEBIT — same read, but **guarded**:
  `IF FINAL-BALANCE >= AMOUNT` else display "Insufficient funds" and do not write. Invariant:
  `STORAGE-BALANCE` never goes negative — enforced only by this guard, not intrinsically, flagged
  as a fragility for the target design to harden. Open item for Phase 3: is `FINAL-BALANCE`
  reused across calls or always freshly read? (CFG alone shows a `READ` at the top of every
  branch, suggesting freshness, but confirming "no call ever skips the READ" requires the
  call-graph view.)
- `DataProgram`: rule — pure key-value READ/WRITE by convention string, no validation of
  `PASSED-OPERATION`, silent no-op if neither READ nor WRITE (`IF/ELSE IF` with no final `ELSE`) —
  edge case: any other 4-char code silently does nothing and leaves `BALANCE` unset/garbage on the
  caller side. Flagged for explicit exception in the target instead of silent no-op.

---

## Phase 3 — Dependency Mapping

**Entry**: Phase 0 raw call graph + Phase 2 per-program specs and open items for all programs in
scope.
**Exit**: resolved static call graph (literal calls bound to concrete PROGRAM-ID targets),
LINKAGE-to-WORKING-STORAGE data-flow map per call edge (which fields are read/written across the
`CALL ... USING` boundary, by position and by PIC-compatibility), shared-state map (WORKING-STORAGE
items that outlive a single paragraph and are implicitly shared across calls within a run unit),
every Phase-2 open item closed with a definitive answer, migration-unit boundary decision (grouping
programs that share such state into one target component).
**Artifacts**: `call-graph-resolved.json`, `dataflow/<edge>.json`, `shared-state.json`,
`spec/open-items-resolved.json`, `migration-units.json`.
**Parallel**: internally parallel per call edge while building the dataflow map; the final
grouping decision is a single sequential step consuming all edges, and it gates every downstream
phase (4 through 8 iterate at the migration-unit grain this phase defines) — so Phase 3 as a whole
cannot overlap with Phase 4.

**Walkthrough**:
- Edge `MainProgram→OperationsProgram`: one positional param, `PIC X(6)` code (`'TOTAL '`,
  `'CREDIT'`, `'DEBIT '`) — a **string-encoded enum acting as an operation selector**, recorded as
  a semantic finding, not just a type.
- Edge `OperationsProgram→DataProgram`: two positional params — `PASSED-OPERATION PIC X(6)`
  (`'READ'`/`'WRITE'`, different literal widths than the outer enum, right-padded) and
  `BALANCE PIC 9(6)V99` passed **by reference** (COBOL default `BY REFERENCE`), meaning
  `DataProgram` mutates `OperationsProgram`'s `FINAL-BALANCE` in place on `READ`.
- Shared-state map: `STORAGE-BALANCE` in `DataProgram` is the single source of truth for account
  balance; `FINAL-BALANCE` in `OperationsProgram` is a **transient copy per call**, never
  persistent across separate `CALL 'OperationsProgram'` invocations from `MainProgram` — this
  closes Phase 2's open item: each menu selection re-enters `OperationsProgram` fresh and
  re-`READ`s before use in all three branches, confirming no request-scoped bug exists. The
  persistence boundary for the target design is exactly `DataProgram`, not `OperationsProgram`.
- Migration unit decision: all 3 programs → **one migration unit** (they share one balance state
  and no program is independently callable/testable without the others).

---

## Phase 4 — Code Conversion

**Entry**: Phase 2 specs + Phase 3 dataflow/shared-state map for the migration unit; target
architecture decision (made once, upstream of this per-file loop): COBOL `PROGRAM-ID` → C# class,
`CALL...USING` → method call or constructor-injected service, `LINKAGE SECTION BY REFERENCE`
params → `ref`/`out` params or mutable DTO, `STORAGE-BALANCE` persistent working-storage → an
injected singleton/scoped `IAccountStore` (in-memory `Dictionary`/single field, matching the
source's own in-memory-only semantics — no false upgrade to file/DB persistence unless separately
requested).
**Exit** (REVISED — user rejected 1:1 mapping; supersedes the original criterion): compiling C#
solution in Clean Architecture layers ({Sln}.Domain / .Application/UseCases / .Infrastructure /
.Cli), one behavior-named handler + port per COBOL program (name derived from Phase 2 extracted
behavior, not the filename), SOLID constraints enforced (methods <50 lines, nesting <=4, dependency
rule inward), output git-versioned per run ULID. Traceability preserved via an explicit
COBOL-program→handler mapping table in CONVERSION-NOTES.md instead of via 1:1 filenames. No behavior
change beyond what Phase 2/3 flagged as an explicit, documented deviation (e.g. hardening the
negative-balance invariant is allowed only if logged as a deliberate deviation, not silent) — the
Parity Gate (Phase 6) remains the proof that restructuring preserved behavior.
**Artifacts**: `src/*.cs`, `CONVERSION-NOTES.md` (one entry per deviation from literal semantics,
with the Phase-2/3 finding it resolves).
**Parallel**: gated by a short sequential **contract-freeze sub-step**, then parallel per class.
- *Contract freeze* — Entry: Phase 3 dataflow map for the unit. Exit: fixed shared interface
  shapes every class-generation task will compile against. Artifact: `contracts/*.cs` (e.g.
  `enum AccountOperation`, `interface IAccountStore`). Parallel: no — single step, ~1 unit of work,
  blocks the parallel fan-out below.
- Once contracts are frozen, `MainProgram.cs`, `OperationsProgram.cs`, `DataProgram.cs` generate
  in parallel against them, and in parallel with all of Phase 5 (Test Generation), which consumes
  the same frozen contracts.

**Walkthrough** (concrete mapping):
- `'TOTAL '`/`'CREDIT'`/`'DEBIT'` string codes → `enum AccountOperation { Total, Credit, Debit }`
  (contract-freeze artifact, since both `MainProgram` and `OperationsProgram` sides must agree).
- `'READ'`/`'WRITE'` → collapsed directly into `IAccountStore.GetBalance()` /
  `IAccountStore.SetBalance(decimal)` — eliminating the string-selector pattern entirely is a
  **documented deviation**, logged in CONVERSION-NOTES.md, because it's a COBOL-era
  calling-convention artifact with no business meaning.
- `PIC 9(6)V99` → `decimal`, scaled/validated to 6 integer + 2 fractional digits at the input
  boundary (`MainProgram`'s amount prompt), not left as unconstrained `decimal`.
- `STORAGE-BALANCE VALUE 1000.00` → `IAccountStore` seeded with `1000.00m`, scoped to app
  lifetime (singleton), explicitly documented as "in-memory only, resets on restart" to preserve
  the source's actual persistence semantics (not silently upgraded).
- Debit guard ported verbatim as `if (store.GetBalance() >= amount)`; the Phase-2-flagged
  fragility (guard-only enforcement) is hardened by moving the check inside
  `IAccountStore.Debit(amount)` itself, and this upgrade is logged as a deviation with the
  invariant it now enforces intrinsically.

---

## Phase 5 — Test Generation

**Entry**: Phase 2 specs/invariants (source of truth for expected behavior — tests must assert
COBOL behavior, not the C# implementation's behavior) and Phase 4's frozen contracts; does not
require Phase 4's class bodies to be finished (test code is written against interfaces before
implementations exist).
**Exit**: test suite covering every branch in the Phase-1 CFGs, every invariant in Phase 2, and
every edge case explicitly enumerated there (invalid menu choice, insufficient funds, boundary
amount exactly equal to balance, zero-amount credit/debit if not explicitly excluded).
**Artifacts**: `tests/*.Tests.cs` (xUnit), `coverage-map.json` (CFG-node → test-case cross-reference,
so Phase 6 can prove structural coverage, not just line coverage).
**Parallel**: fully parallel with Phase 4's class generation (both consume the same frozen
contracts; test authoring does not depend on implementation bodies). Internally parallel per
program's test class.

**Walkthrough**: `AccountStoreTests` — seed=1000.00, `GetBalance()` returns 1000.00;
`SetBalance(1234.56)` then `GetBalance()` returns 1234.56. `OperationsProgramTests` — Credit(500)
on 1000 → 1500; Debit(500) on 1000 → 500; Debit(1500) on 1000 → unchanged, "insufficient funds"
path taken (assert store NOT written, matching source's no-write-on-failure behavior exactly).
`MainProgramTests` — choice 4 exits loop; choice 5/0/non-numeric → "Invalid choice" path, loop
continues (directly encodes the Phase-2 edge case about `ACCEPT`/`PIC 9` truncation semantics).

---

## Phase 6 — Parity Validation

**Entry**: Phase 4 conversion complete (compiles) AND Phase 5 tests complete.
**Exit**: test suite passes against the C# implementation; where feasible, differential/oracle
testing against the actual compiled COBOL binary (same input sequences, same-shape output diffed)
for the scenarios enumerated in Phase 5; 100% of Phase-1 CFG branches hit (per `coverage-map.json`);
every CONVERSION-NOTES.md deviation has an explicit test proving the *new* behavior (not the old
one) so deviations are asserted, not just documented. **Failure route**: any failing scenario or
uncovered branch sends the unit back — to Phase 2 if the failure reveals a missed/misunderstood
business rule, to Phase 3 if it reveals a missed dependency/state-sharing fact, or to Phase 4 if
it is a pure implementation defect against an already-correct spec; Phase 6 is always re-run in
full after any such fix, never partially re-checked.
**Artifacts**: `parity-report.md` (pass/fail per scenario, per-deviation justification cross-check),
`oracle-diff/*.txt` (COBOL-vs-C# transcript diffs, if a COBOL runtime is available to execute
against).
**Parallel**: sequential gate — consumes both Phase 4 and Phase 5 outputs, cannot start before
both finish. Internally, running the oracle COBOL binary and running the C# suite are two
independent parallel sub-steps whose outputs are then diffed serially.

**Walkthrough**: run GnuCOBOL-compiled `main.cob` chain with scripted input `2\n500\n1\n4\n` (credit
500, view balance, exit) → captures "Amount credited. New balance: 001500.00" (COBOL zero-padded
`PIC 9(6)V99` display format). C# equivalent must either reproduce that exact display format or the
deviation ("`1500.00` instead of `001500.00`, formatting only, no business-logic change") is logged
and surfaced — not silently accepted — for disposition at the Phase 7 human gate.

---

## Phase 7 — Human Approval Gate

**Entry**: Phase 6 parity report complete, all Phase-5 tests green, all CONVERSION-NOTES.md
deviations individually justified with a passing test.
**Exit**: human reviewer has read `parity-report.md` + `CONVERSION-NOTES.md`, explicitly approved
or requested changes per deviation; approval recorded (who, when, which report hash) — the only
phase requiring a human in the loop by design, everything upstream is agent-autonomous.
**Artifacts**: `APPROVAL.md` (signed-off report hash + reviewer identity + timestamp + per-deviation
disposition: accept / reject-needs-rework), or a rejection routes back to Phase 2 (if the rejected
deviation reveals a missed business rule), Phase 3 (missed dependency fact), or Phase 4 (pure
implementation fix) — never past Phase 6 without re-running it.
**Parallel**: strictly sequential and blocking — no downstream phase runs until this gate clears;
this is intentional, not an optimization target.

**Walkthrough**: reviewer sees the `IAccountStore.Debit` invariant-hardening deviation and the
display-format deviation; approves both (hardening is a strict improvement, formatting is cosmetic
and documented) and signs off.

---

## Phase 8 — Merge

**Entry**: Phase 7 approval recorded.
**Exit**: C# code merged to target branch/repo, CI green, migration-unit marked "migrated" in the
overall project tracking artifact (relevant when more than one unit exists; for this demo, unit=
whole app, so this is also project completion).
**Artifacts**: merge commit, updated `migration-units.json` status field, final `RELEASE-NOTES.md`
summarizing the unit (source LOC, target LOC, deviation count, test count).
**Parallel**: sequential, single unit — trivial here. In a multi-unit repo, Phase 8 for unit A can
run while unit B is still in Phase 2, since units are independent once Phase 3 has drawn
boundaries correctly (the real, systemic parallelism opportunity across the whole pipeline is
across units, not within one).

---

## Sequencing Summary

```
Phase 0 (Discovery)               [parallel: per file]
   │
Phase 1 (Structural Analysis)     [parallel: per program]  ── gates Phase 2
   │
Phase 2 (Business Logic Extraction) [parallel: per program]  ── open items → Phase 3
   │
Phase 3 (Dependency Mapping)      [parallel per edge; sequential grouping decision]
   │  (defines migration-unit grain for everything below)
   │
   ├── contract freeze (sequential, short)
   │            │
   ┌────────────┴────────────┐
Phase 4 (Code Conversion)   Phase 5 (Test Generation)
   [parallel per class]       [parallel per test class]
   (both parallel to each other, both gated on contract freeze)
             │
             └────────────┬────────────┘
                           ▼
              Phase 6 (Parity Validation)   [sequential gate; failure → Phase 2/3/4]
                           ▼
              Phase 7 (Human Approval Gate) [sequential, blocking; rejection → Phase 2/3/4]
                           ▼
              Phase 8 (Merge)               [sequential per unit;
                                              parallel ACROSS units]
```

**Cross-unit parallelism** (the only pipeline-level parallelism that scales past this 3-file demo):
once Phase 3 has drawn migration-unit boundaries for the whole repo, every unit runs Phases 4–8
independently and concurrently; only Phase 0 and Phase 3 are inherently whole-repo-scoped (Phase 0
because you need every file to classify any file's role; Phase 3 because unit boundaries require
seeing the full resolved call graph before any single unit can be said to be "closed"). Phases 1
and 2 are per-program and can run for any file as soon as it is discovered, independent of other
units' progress.
