# 06 — Parity / Differential / Golden-Master Testing Layer

Status: design only, no implementation. Target system: `cobol-accounting-system`
(`main.cob`, `operations.cob`, `data.cob`, in-memory `STORAGE-BALANCE`, VALUE 1000.00
seed, PIC 9(6)V99 fixed-point, single-session process, no persistence across runs).
Target migration: generated C# (Node.js port already exists as reference in
`node-accounting-app/`; C# is a second, LLM-generated target this layer must gate).

## 1. Purpose and non-goals

Purpose: mechanically prove the migrated C# reproduces the COBOL's *observable
behavior* — same stdout transcript shape, same numeric results, same edge-case
decisions (insufficient funds, invalid menu choice) — under identical input
sequences, before any migrated code is trusted as a drop-in replacement.

Non-goals: this layer does not judge code quality, architecture, or idiomaticity
of the C# output. It does not replace unit tests of the C# code in isolation
(covered elsewhere, e.g. `05-*` unit-test docs from `d05-unittest`). It is purely
a black-box behavioral equivalence oracle, run at the process-I/O boundary.

## 2. Why differential testing, not translated unit tests

Hand-porting the COBOL's implicit semantics into C# unit test assertions bakes
in the *migrator's* understanding of correctness, which is exactly what needs
verification. Differential/golden-master testing sidesteps this: the COBOL
binary itself — compiled once via GnuCOBOL and frozen — is the oracle. Any
disagreement between oracle and candidate is a signal to classify, not
adjudicate from a spec. This mirrors:

- **Golden-master / characterization testing** (Feathers): capture actual
  legacy output for a broad input corpus, treat it as ground truth, diff future
  candidates against it. Applies directly here since the COBOL has no
  spec doc beyond the informal `TESTPLAN.md`.
- **Locksmith Loop** pattern (deterministic student + LLM teacher for "locked"
  paragraphs): the COBOL PROCEDURE DIVISION paragraphs (`MAIN-LOGIC`, the
  IF/ELSE IF chain in `OperationsProgram`, the READ/WRITE branch in
  `DataProgram`) are the "locked" reference behavior. The C# candidate is the
  student. A deterministic harness (this doc) does the bulk of verification;
  an LLM teacher is invoked only to *classify* a small set of residual
  divergences that pure diffing cannot resolve (see §6).
- **Differential test generation (Mokav/DiffSpec style)**: rather than a
  fixed hand-written input list, generate an input corpus programmatically
  (equivalence classes + boundary values + adversarial/random sequences) and
  run both systems on every generated case, harvesting divergences as the
  test signal itself instead of writing expected-output assertions by hand.

## 3. System under test: interfaces and determinism envelope

### 3.1 COBOL process shape
- Single executable `accountsystem` (linked from `main.cob` + `operations.cob`
  + `data.cob`), REPL loop over stdin/stdout, terminates on menu choice 4 or
  EOF on stdin.
- State: `STORAGE-BALANCE` in `DataProgram`'s WORKING-STORAGE, PIC 9(6)V99,
  initialized to `1000.00` at process start, mutated only via
  `CALL 'DataProgram' USING 'WRITE', ...`. State is **not persisted** — it
  resets to 1000.00 every process launch. This is the single most important
  fact for the harness: parity is defined per-process-run, seeded at 1000.00,
  not across runs.
- Inputs consumed via `ACCEPT`: one `PIC 9` digit for menu choice (single
  numeric character — GnuCOBOL `ACCEPT` truncates/rejects non-numeric per
  runtime), one `PIC 9(6)V99` for credit/debit amount (numeric literal read as
  unformatted decimal text line, e.g. `200.00`).
- Outputs: `DISPLAY` statements only, line-buffered stdout. No stderr use, no
  exit codes differentiated (GnuCOBOL default STOP RUN exit code 0 in all
  paths observed — this must be verified empirically, see §4.2).

### 3.2 Non-determinism sources to neutralize
- None identified in the COBOL source itself: no timestamps, no random
  values, no file I/O, no environment variable reads. This program is fully
  deterministic given its input stream — a favorable condition for exact-match
  diffing rather than approximate/statistical comparison.
- Risk in the C# candidate: LLM-generated migrations commonly introduce
  incidental non-determinism the COBOL never had — `DateTime.Now` in a log
  line, culture-variant `decimal.ToString()` formatting (`,` vs `.` decimal
  separator under non-invariant `CultureInfo`), `Console.WriteLine` line-ending
  differences (`\r\n` vs `\n`). The harness must normalize known-benign
  representation differences (§6.3) rather than let them either false-fail or
  get silently ignored.

## 4. Harness architecture

### 4.1 Two runners behind one driver interface

```
                    +---------------------+
 input sequence --> |  Parity Driver      | --> divergence report
                    | (Python/pytest or   |
                    |  .NET xUnit + proc) |
                    +---------------------+
                       |                |
             spawns    |                |  spawns
                       v                v
            +--------------+   +------------------+
            | GnuCOBOL bin |   | C# candidate      |
            | ./accountsys.| | dotnet run / .exe  |
            +--------------+   +------------------+
                stdin/stdout       stdin/stdout
```

Both targets are launched as child processes per test case (fresh process =
fresh 1000.00 balance, matching COBOL's actual reset semantics — do NOT reuse
a long-lived process across cases, or the oracle's real behavior is lost).

Driver responsibilities:
1. Compile/locate the frozen COBOL oracle binary (pin the GnuCOBOL version —
   e.g. `cobc (GnuCOBOL) 3.2` — in a manifest; recompiling with a different
   compiler version is itself a change to the oracle and must be re-baselined,
   not silently trusted).
2. For each test case: write the full input script to both processes' stdin
   (newline-delimited, exactly one token per `ACCEPT`), capture stdout+exit
   code+stderr+wall time from both.
3. Normalize both transcripts (§6.3).
4. Diff normalized transcripts; classify divergence if any (§6).
5. Emit a structured verdict record (JSON) per case: `{case_id, inputs, cobol_output,
   csharp_output, verdict: PASS|DIVERGE, divergence_class, diff}`.

### 4.2 Concrete invocation

COBOL side (build once, cache artifact, hash-pin it):
```
cobc -x main.cob operations.cob data.cob -o accountsystem
```
Confirm GnuCOBOL emits a single linked executable for this call form (the
README's separate `-c`/link steps are equivalent to this one-shot form; verify
with `cobc --version` pinned and a smoke run before trusting the harness).

C# side: candidate must expose the same process contract — a console app
reading digit-then-optional-amount from stdin, writing to stdout. If the
generated C# is structured as separate assemblies mirroring the three COBOL
programs, the parity harness treats the *linked whole* as the unit under test
(black box), not the internal call boundaries — internal-boundary parity (does
`OperationsProgram.cs` get called the way `operations.cob` was called) is an
architecture-fidelity concern for a different doc, not this one.

### 4.3 Input corpus construction (differential generation)

Rather than hand-listing cases, derive them from the COBOL's own decision
points, mechanically enumerated from the paragraphs:

| Decision point | Source | Equivalence classes |
|---|---|---|
| Menu choice | `main.cob` EVALUATE | {1,2,3,4} valid; {0,5,9} invalid-but-in-range; non-digit / multi-char (harness-level, since PIC 9 truncates) |
| Credit amount | `operations.cob` ADD | 0.00; smallest unit 0.01; typical (100.00); large near PIC 9(6) ceiling (999999.99); overflow attempt (1000000.00, exceeds 6 integer digits) |
| Debit amount vs balance | `operations.cob` IF FINAL-BALANCE >= AMOUNT | amount < balance; amount == balance (boundary, exact zero-out); amount > balance by 0.01 (boundary insufficient-funds); amount == 0.00 |
| Sequence effects | cross-operation | credit then debit then view (compounding); multiple credits before a view; debit-fail then debit-success (state must be unaffected by the failed attempt) |
| Loop termination | `main.cob` PERFORM UNTIL | exit immediately (choice 4 first); invalid choice then exit; EOF on stdin with no choice 4 (should terminate, not hang) |
| Malformed numeric input | `ACCEPT AMOUNT` | non-numeric text where amount expected, negative sign, decimal with >2 fractional digits, empty line |

Each row generates a family of concrete multi-step scripts (a "scenario" =
ordered list of menu selections + amounts). Target ~40–60 scenarios total for
this program's size: boundary values dominate (per swap-table discipline,
n=1 is not evidence — every equivalence class needs at least 2 independent
scenarios exercising it from different prior states, e.g. insufficient-funds
tested both from the seed balance and after a prior credit).

Malformed-input classes are high value: GnuCOBOL's `ACCEPT` and a C# `int.Parse`/
`decimal.Parse` port diverge easily (crash vs silent zero vs exception message)
and are exactly where "hallucinated" migration behavior hides.

## 5. Parity Gate: pass/fail criteria

The Parity Gate is a CI-blocking check (ties into `r9-cicd-gating`'s gating
design — this doc defines the check's semantics, not its pipeline wiring).

**Gate PASSES for a scenario iff**, after normalization (§6.3):
1. Final numeric balance state agrees exactly (compared as the underlying
   scaled integer, i.e. cents: `104999` not `"1049.99"` string) after every
   operation in the scenario, not just at the end — a divergence that
   self-cancels by the final `DISPLAY` must still fail the gate.
2. The classified *decision* taken at each branch point agrees: same menu
   branch executed, same credit/debit accept/reject outcome, same
   insufficient-funds determination. Decision agreement is checked
   independently of the exact wording of the message (§6.3), because wording
   is representation, not decision.
3. Loop termination agrees: same number of menu iterations before the process
   exits, exit happens on the same triggering input.
4. Process exit status agrees in category (clean exit vs. crash/nonzero) —
   exact numeric exit code equality is not required unless both are
   documented as meaningful (GnuCOBOL's default is uninformative here).

**Gate FAILS** (blocks merge/promotion of that code path) when any of the
above disagree AND the divergence is classified `REAL_BUG` (§6.1). A `DIVERGE`
classified `INTENTIONAL_CHANGE` or `REPRESENTATION_DIFFERENCE` does not fail
the gate but MUST be logged to a durable divergence ledger (append-only file,
one row per accepted divergence, with reviewer sign-off reference) so silent
scope creep in "intentional" changes is itself auditable over time.

**Gate criteria at corpus level**: 100% of generated scenarios must reach a
verdict (no scenario may be silently dropped for being "hard to automate" —
if a scenario can't be scripted, that itself is logged as a coverage gap, not
skipped). No minimum pass percentage below 100% is acceptable for this
program's size — this is a 3-file, single-balance system; every one of ~50
scenarios is cheap enough that partial-credit thresholds (appropriate for
larger migrations) do not apply here. Larger migrations under the same
pipeline should define a per-module pass-rate floor plus a zero-tolerance list
for money-arithmetic and authorization-decision paragraphs specifically.

## 6. Divergence classification

Every diff between COBOL and C# transcripts must be assigned exactly one class
before the gate verdict is finalized. Default classification is `REAL_BUG`;
promotion to the other two classes requires explicit evidence, not default
trust in the migration.

### 6.1 REAL_BUG (blocks gate)
A divergence traceable to the C# code producing a different *decision* or
different *numeric result* than the COBOL, with no evidence the difference was
deliberate. Examples for this program:
- Off-by-one on the debit boundary: COBOL uses `>=` (`FINAL-BALANCE >= AMOUNT`
  succeeds when balance equals amount exactly); a C# port using `>` would
  reject a valid exact-balance debit — this is the single highest-risk
  paragraph in the program and must have a dedicated boundary scenario.
  [flag for `r3-cobol-semantics` to confirm GnuCOBOL numeric-compare semantics
  on PIC 9(6)V99, including any truncation/rounding on the COMP-3 vs display
  numeric representation, before assuming C# `decimal` comparison is bit-for-bit
  equivalent]
- Silent truncation difference: COBOL `PIC 9(6)V99` truncates (does not round)
  values with more than 2 fractional digits or more than 6 integer digits on
  `ACCEPT`/`MOVE`; a naive C# `decimal.Parse` + no truncation would preserve
  extra precision the COBOL never had — producing a balance that "looks more
  correct" but is not equivalent.
- Menu choice normalization difference: COBOL's `PIC 9` `ACCEPT` on
  multi-character or non-numeric stdin has defined-but-easy-to-miss GnuCOBOL
  behavior (commonly: takes the last digit, or a runtime error depending on
  compile flags); a C# `int.TryParse` returning `false`→"invalid choice" is
  only equivalent if the COBOL's own path also lands on `WHEN OTHER`.
- State leakage the COBOL doesn't have: e.g. C# balance persisted to disk/DB
  across process runs when COBOL always resets to 1000.00 — this is a full
  contract violation, not merely a representation issue.

### 6.2 INTENTIONAL_CHANGE (does not block gate, logged)
A divergence the team has explicitly decided is a desired improvement over
the legacy behavior, e.g.:
- Better validation messaging for malformed numeric input (COBOL likely
  crashes or silently misbehaves on non-numeric `ACCEPT`; C# rejecting with a
  clear error is an accepted upgrade) — requires a linked decision record
  (ADR or ticket) before acceptance, never accepted purely on the migrator's
  say-so.
- Support for a wider amount range than PIC 9(6)V99's cap, if the business
  has explicitly asked for it as part of the migration scope.

Any item here requires: (a) a written rationale referencing the specific
scenario, (b) sign-off recorded in the divergence ledger, (c) the scenario
itself updated in the corpus with an explicit "expected divergence" marker so
future re-runs don't re-flag it as unclassified.

### 6.3 REPRESENTATION_DIFFERENCE (does not block gate, auto-normalized)
Differences in *how* the same decision/value is rendered, not in the decision
or value itself. These should be handled by the harness's normalization step
before diffing even reaches classification, but must be explicitly enumerated
and tested (a normalizer nobody validated is itself a bug source):
- Numeric formatting: `1200.00` vs `1,200.00` vs `1200.0` vs `1200,00`
  (culture) — normalize by parsing both sides to a canonical decimal/cents
  integer before comparison, never compare formatted strings for the balance
  line.
- Line endings (`\n` vs `\r\n`), trailing whitespace, prompt punctuation
  wording ("Enter your choice (1-4): " vs "Enter your choice (1-4):") —
  normalize via whitespace-collapse + trailing-colon-and-space stripping.
- Menu banner cosmetics (dashes count, capitalization of "Goodbye!") — these
  are compared only for *presence of the same semantic message*, matched by
  a small regex/keyword table per message (e.g. any line containing both
  "balance" and the numeric value counts as the balance-report line),
  not literal string equality.
- Message ordering when two `DISPLAY`s in the COBOL are logically one
  compound message split differently in C# (e.g. COBOL's two-line "Amount
  debited. New balance: X" split as one DISPLAY with a line continuation vs.
  C# emitting two `Console.WriteLine`s) — normalize by concatenating
  same-turn output before comparison rather than per-line diffing.

The normalizer itself needs its own small test suite (a handful of known-benign
pairs that must normalize equal, and known-bad pairs that must NOT normalize
equal) — an over-eager normalizer is a silent way to hide `REAL_BUG` cases,
which is worse than no normalizer.

### 6.4 Escalation path (Locksmith-style teacher call)
When automated normalization + rule-based classification cannot confidently
place a divergence in 6.1–6.3 (e.g. ambiguous wording change that might hide a
numeric difference), escalate to an LLM-based classifier given: the exact
paragraph of COBOL source, the exact C# method, both raw transcripts, and the
proposed classification with reasoning required. This is the "teacher" role
in the Locksmith Loop analogy — invoked only on the residual ambiguous set,
never as the primary oracle (the compiled COBOL binary remains the primary
oracle; the LLM never gets to override a clear REAL_BUG determination, only
to help classify borderline representation/intentional cases). Every
teacher-assisted classification must still be logged in the divergence ledger
with the model's reasoning attached, and is subject to human review before
being trusted as INTENTIONAL_CHANGE or REPRESENTATION_DIFFERENCE.

## 7. Reporting artifact

Per run, emit:
- `parity-report.json`: full structured verdicts, one entry per scenario, per
  §4.1 step 5's schema.
- `parity-report.md` (generated from the JSON, human-facing): scenario count,
  pass/fail/diverge-accepted counts, list of any `REAL_BUG` verdicts with
  inline diff, link to divergence ledger entries touched this run.
- Divergence ledger (`divergence-ledger.jsonl`, append-only, never rewritten):
  one line per ever-accepted `INTENTIONAL_CHANGE`/`REPRESENTATION_DIFFERENCE`,
  keyed by scenario id + code revision hash, so a later re-audit can trace
  exactly when and why a divergence was accepted rather than re-litigating it
  from scratch.

## 8. Open items for adjacent workstreams

- `r3-cobol-semantics`: confirm exact GnuCOBOL truncation/rounding and
  numeric-compare semantics for PIC 9(6)V99 used throughout §6.1, and confirm
  `ACCEPT` behavior on non-numeric/multi-digit input for PIC 9 — both are
  load-bearing assumptions in this design that must be verified against the
  actual compiler, not assumed from the COBOL standard.
- `r9-cicd-gating`: wire the Parity Gate's PASS/FAIL verdict (§5) into the
  pipeline as a required check; this doc defines the check's semantics only.
- `r10-test-generation`: this doc's §4.3 corpus table is a starting
  enumeration, not exhaustive — hand off to differential-generation tooling
  (Mokav/DiffSpec-style mutation of the scenario table) for scale once the
  harness skeleton exists.
- `d05-unittest`: this layer is complementary to, not a replacement for,
  C#-internal unit tests; no overlap intended beyond both using the same
  boundary-value catalogue in §4.3.
