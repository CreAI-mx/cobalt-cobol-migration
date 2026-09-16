# 05 — Unit Testing Strategy for Migrated C# Code

Status: design (not implemented). Scope: the agentic COBOL→C# migration pipeline, demo target
`cobol-accounting-system` (`operations.cob`, `data.cob`/`DataProgram`, main dispatch program).

## 1. Objective and non-negotiables

Every migrated C# file/class must ship with an auto-generated xUnit test class *before* it is
accepted into the target tree. Acceptance is gated on:

1. Compilation of the migrated file + its generated tests.
2. A coverage threshold (§3) measured on the migrated file only (not the whole project).
3. Zero failing tests, zero skipped tests without an explicit `[Fact(Skip=...)]` justification
   that references an open ticket.
4. Presence of the mandatory COMP-3/decimal edge-case suite for any migrated field that was
   `PIC 9...V99 COMP-3` (or unpacked `PIC 9...V99`) in the source COBOL (§5).

The test generator is a pipeline stage, not an optional add-on — it runs in the same agent turn
that emits the migrated `.cs` file, against that file only, so a reviewer never sees production
code without its test class.

## 2. Pipeline placement

```
COBOL source (.cob)
   │
   ▼
[Stage: Parse+IR]  (r8-cobol-parsers) — AST + copybook-resolved field metadata
   │
   ▼
[Stage: Transform]  (codex-migration) — emits <ClassName>.cs
   │
   ▼
[Stage: Test-Gen]  (r10-test-generation) — emits <ClassName>Tests.cs
   │  inputs: migrated .cs AST, original COBOL AST (for PIC clause provenance),
   │          field-level decimal/scale metadata carried through Transform as
   │          annotations (see §5.1)
   ▼
[Stage: Build+Coverage Gate]  (r9-cicd-gating) — dotnet build, dotnet test,
   │  coverlet coverage collection, threshold check
   ▼
accepted (merged into target project) | rejected (returned to Transform with
   failure report: failing assertions, uncovered branches, missing edge cases)
```

The Test-Gen stage never runs standalone against hand-written code — it is always paired 1:1
with a Transform-stage output in the same commit/PR unit, so a migrated class and its tests are
never reviewed or merged separately.

## 3. Coverage thresholds (gate, not aspiration)

Measured with Coverlet (`coverlet.msbuild` or `coverlet.collector` + `reportgenerator`), scoped
per migrated file via `[ExcludeFromCodeCoverage]` on everything else in the assembly during the
gate check (or an include-filter `/p:Include="[TargetAssembly]TargetNamespace.ClassName"`).

| Metric | Threshold | Rationale |
|---|---|---|
| Line coverage (migrated class) | ≥ 90% | COBOL procedure-division logic is small, branch-dense; 90% is achievable without padding tests |
| Branch coverage (migrated class) | ≥ 85% | Every `IF`/`ELSE IF` chain from COBOL (e.g. TOTAL/CREDIT/DEBIT) must have both arms exercised |
| Line coverage (whole target project, rolling) | ≥ 80% | Matches org-wide testing.md floor; prevents drift as files accumulate |
| Mutation score (Stryker.NET, sampled) | ≥ 60%, informational only in v1 | Catches assertion-free tests that inflate line coverage without checking values; not a hard gate initially — logged, promoted to gate once baseline is established |

**Why line coverage alone is insufficient here:** COBOL numeric edge cases (exact boundary,
rounding, truncation) can execute a covered line while asserting nothing meaningful. Branch
coverage plus the mandatory decimal-edge-case catalogue (§5) is the real gate; line/branch % is
the automated proxy, decimal-case presence is checked structurally (§5.3), not just numerically.

A file below threshold is **rejected** back to Test-Gen with the uncovered branch list (from the
Coverlet/OpenCover XML) fed back as generation targets — not silently merged with a lower bar.

## 4. Test generation strategy per migrated file/class

### 4.1 Source of test cases

The generator does not invent test cases from the C# code alone (that only proves the C# is
self-consistent, not that it matches COBOL behavior). Instead it derives cases from three
sources, in priority order:

1. **COBOL control-flow enumeration** — every `IF`/`EVALUATE` branch in the original `.cob`
   becomes at minimum one `[Fact]` or one row of a `[Theory]`/`[MemberData]` set, named after the
   branch condition (e.g. `OPERATION-TYPE = 'CREDIT'` → `Execute_CreditOperation_...`).
2. **Field domain boundaries from PIC clauses** — `PIC 9(6)V99` implies domain
   `[0.00, 999999.99]` with 2 decimal places; generator emits boundary cases (min, max, zero,
   one-cent-below-max) automatically from the copybook/field metadata, not from guessing at the
   C# type.
3. **Literal/behavioral evidence from any existing `.txt`/sample I/O fixtures** in the source
   repo (screen captures, JCL test decks) — used as golden values when present, else synthesized.

### 4.2 Per-class layout convention

One test file per migrated class, xUnit, colocated by mirrored namespace:

```
src/Accounting.Operations/OperationsProgram.cs
tests/Accounting.Operations.Tests/OperationsProgramTests.cs
```

Class/method naming: `MethodUnderTest_Scenario_ExpectedOutcome` (already the house convention —
`csharp-testing` skill). One `IClassFixture<T>` per migrated program if the COBOL program held
`WORKING-STORAGE` state across calls (COBOL working-storage is effectively instance state for the
migrated class); a fresh instance per `[Fact]` otherwise, since COBOL `PROCEDURE DIVISION` called
fresh per invocation (as in `OperationsProgram`, which takes `PASSED-OPERATION` and has no
persisted linkage) maps to a stateless method or a class instantiated per test — no shared
mutable fixture unless the source program's calling convention requires it (verify against the
COBOL `CALL`/`GOBACK` pattern, not assumed).

### 4.3 Mocking external dependencies

`CALL 'DataProgram' USING 'READ'/'WRITE', FINAL-BALANCE` migrates to an injected
`IAccountDataStore` (or equivalent) interface. Test-Gen must:
- Generate the interface extraction as part of Transform (not Test-Gen) so migrated code is
  testable at all — a static/direct call to a migrated `DataProgram` class is not mockable and
  fails review under `code-review.md` (testability is a code-quality checklist item).
- Use Moq (`Moq` package, house default per `.NET` conventions) to stub `Read()`/`Write(decimal)`
  and assert call counts/arguments (`Verify(x => x.Write(1050.00m), Times.Once)`), because the
  COBOL `WRITE` side effect is the observable behavior being tested, not just the return value.

### 4.4 xUnit/NUnit convention decision

**xUnit is the standard** for this migration target. Rationale: no `[SetUp]`/`[TearDown]`
lifecycle needed (COBOL programs generally migrate to stateless-per-call methods, so constructor
injection + `IDisposable` covers it); `[Theory]`/`[InlineData]`/`[MemberData]` map cleanly onto
COBOL `EVALUATE`/multi-branch `IF` chains and onto PIC-clause boundary tables; xUnit is Microsoft's
own default for new .NET projects (`dotnet new xunit`) and is what `csharp-testing`/`.NET`
skill conventions in this org standardize on. NUnit is not used unless a target repo already
standardizes on it — the generator must detect `*.csproj` `PackageReference` for `NUnit` vs
`xunit` before emitting and follow the existing convention if the target solution predates the
migration (never introduce a second framework into one solution).

Package set: `xunit`, `xunit.runner.visualstudio`, `Moq`, `coverlet.collector`,
`Microsoft.NET.Test.Sdk`, `FluentAssertions` (house-preferred, but plain `Assert.Equal` acceptable
if the target repo has no `FluentAssertions` reference already — do not add a new assertion
library to a repo that doesn't have one without an explicit decision).

Conventions:
- `[Theory]` + `[InlineData]` for the amount/boundary matrix (§5.2).
- `[Fact]` for single named branches (TOTAL, insufficient-funds path).
- Arrange-Act-Assert with blank-line separation and `// Arrange` / `// Act` / `// Assert`
  comments, per `testing.md`.
- No `Thread.Sleep`; COBOL `ACCEPT`/`DISPLAY` I/O is abstracted behind an injected
  `IConsoleIO` (or `TextReader`/`TextWriter`) so tests don't touch `Console`.

## 5. COMP-3 / decimal precision edge cases

### 5.1 Metadata carried from COBOL to guide generation

`AMOUNT PIC 9(6)V99` and `FINAL-BALANCE PIC 9(6)V99` (unpacked here; `COMP-3` packed-decimal
fields elsewhere in the estate carry identical semantics — implicit decimal point, fixed
scale, no sign in this program since `PIC 9` not `PIC S9`). Transform must annotate the migrated
C# field with the source PIC clause as a code comment or attribute
(`// COBOL: PIC 9(6)V99, unsigned, scale=2, COMP-3=false`) so Test-Gen can read domain bounds
without re-parsing the `.cob`. The migrated CLR type must be `decimal`, never `double`/`float`
(binary floating point cannot represent COBOL's exact decimal scale — this is a CRITICAL-severity
finding under `security.md`/`code-review.md`'s "no hardcoded... data loss risk" framing if a
migration emits `double` for a COMP-3 field).

### 5.2 Mandatory boundary/edge matrix (per migrated decimal field)

For every migrated field carrying `PIC 9(6)V99` provenance, Test-Gen emits an `[InlineData]`
matrix covering, at minimum:

| Case | Value | Purpose |
|---|---|---|
| Zero | `0.00m` | Additive identity; guards against null/default confusion |
| One cent | `0.01m` | Minimum representable unit at scale=2 |
| Max domain value | `999999.99m` | `PIC 9(6)V99` upper bound; overflow-adjacent |
| Max minus one cent | `999999.98m` | Off-by-one-unit boundary just under max |
| Exact balance match (debit) | `AMOUNT == FINAL-BALANCE` | COBOL `IF FINAL-BALANCE >= AMOUNT` uses `>=`; exact equality must debit successfully, not reject |
| One cent over balance (debit) | `AMOUNT == FINAL-BALANCE + 0.01m` | Must hit "Insufficient funds", proves `>=` boundary is not `>` |
| Rounding-hazard input | e.g. `100.005m` truncated/rejected pre-conversion | COBOL `ACCEPT` into `PIC 9(6)V99` truncates to 2 decimals with no rounding; migrated `decimal.Parse`/binding must reproduce truncation, not `MidpointRounding` — assert the *truncating* behavior explicitly, since C# `decimal` arithmetic defaults differ from COBOL `MOVE`/`ACCEPT` truncation semantics |
| Negative input rejected | `-50.00m` | `PIC 9(6)V99` is unsigned; migrated validation must reject or the migrated type must be unable to hold negative values — assert explicitly, do not assume the CLR `decimal` (which is signed) enforces this for you |
| Scale overflow (3rd decimal) | `10.001m` supplied to a scale=2 field | Must truncate/reject per COBOL semantics, not silently round to `10.00m` via default `decimal` display formatting while retaining `10.001m` internally (a common migration bug: storing full precision but *displaying* truncated, so a later `ADD`/`SUBTRACT` uses hidden extra precision the COBOL original never had) |

### 5.3 Structural check for edge-case presence (part of the coverage gate)

Because a numeric edge case can pass through a covered line without ever being *asserted*
correctly (see §3), the Build+Coverage Gate stage additionally runs a static check over the
generated test file: for every field flagged with decimal/COMP-3 provenance in §5.1, the test
class must contain at least one `[InlineData]`/assertion referencing each of the nine rows in
§5.2 (matched by a generation-time manifest comment, e.g. `// EDGE-CASE: max-domain-value`,
emitted alongside each `[InlineData]` row so the check is a manifest diff, not fragile regex
value-matching). Missing rows reject the file back to Test-Gen with the specific missing case
named — this is what prevents "90% line coverage, wrong money" from ever reaching the
accepted-file gate.

### 5.4 Credit / debit / insufficient-funds specific cases (operations.cob)

Directly against `operations.cob`'s three branches, the generated `OperationsProgramTests.cs`
must include (`DataProgram` mocked per §4.3):

- `Execute_Total_DisplaysCurrentBalanceFromDataStore` — verifies `Read()` called once, `Write()`
  never called (TOTAL is read-only).
- `Execute_Credit_AddsAmountAndPersistsNewBalance` — `[Theory]` over the §5.2 matrix, asserting
  `Write(balance + amount)` called with the exact expected `decimal`.
- `Execute_Credit_AtMaxDomainValue_DoesNotOverflowOrWrap` — balance near `999999.99m` plus a
  credit that would exceed the `PIC 9(6)V99` domain; migrated code must reproduce COBOL's
  truncation/size-error behavior (COBOL `ADD` without `ON SIZE ERROR` silently truncates
  high-order digits — this is a genuine COBOL footgun the migration must either preserve
  explicitly and document, or deliberately fix and flag as a behavior change; either choice must
  have an explicit test asserting the chosen behavior, not an untested assumption).
- `Execute_Debit_SufficientFunds_SubtractsAndPersists` — `[Theory]` including the exact-balance
  boundary case from §5.2.
- `Execute_Debit_InsufficientFunds_DisplaysMessageAndDoesNotPersist` — asserts `Write()` is
  **never** called (COBOL's `ELSE` branch has no `WRITE`) — this is a common migration bug where
  a translated `if/else` accidentally calls the persistence method on both branches.
- `Execute_Debit_ExactlyOneCentShort_RejectsDebit` — the off-by-one-unit boundary, directly
  exercising the `>=` vs `>` COBOL semantic.
- `Execute_UnrecognizedOperationType_NoOperationPerformed` — COBOL's implicit `END-IF` with no
  final `ELSE` means an unmatched `OPERATION-TYPE` falls through silently; migrated code must
  match that (no exception, no default branch executed) unless the migration deliberately adds
  validation, in which case the added behavior gets its own test and must be called out in the
  migration diff/PR description, not left implicit.

## 6. Rejection / feedback loop

On gate failure, `r9-cicd-gating` returns to `r10-test-generation`:
- Coverlet branch-miss report (file:line of uncovered branches).
- §5.3 manifest diff (missing edge-case tags).
- Any `dotnet test` failure output verbatim.

Test-Gen regenerates only the missing pieces (append-only where possible) rather than
regenerating the whole test file, to keep prior human review comments on unaffected tests valid.
A file cycles through generation at most 3 times before escalating to human review with the full
failure history attached — silent infinite retry is not acceptable per `hooks.md`/agent-completion
norms.

## 7. Open items for implementation phase

- Decide whether Stryker.NET mutation score becomes a hard gate after N migrated files establish
  a baseline (currently informational, §3).
- Decide instance-vs-static migration pattern for COBOL programs with `WORKING-STORAGE` state
  that *is* expected to persist across `CALL`s within a session (not the case for
  `OperationsProgram`, but likely the case elsewhere in the estate) — affects `IClassFixture`
  usage in §4.2.
- Confirm target repo's existing test framework (xUnit vs NUnit) before first Test-Gen run against
  `cobol-accounting-system`'s eventual `.csproj` — none exists yet as of this writing, so xUnit is
  the default per §4.4.
