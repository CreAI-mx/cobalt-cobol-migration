# 07 — End-to-End Demo: Agentic COBOL→C# Migration Pipeline

Status: design (not implemented). Demo target: `/home/frg/creai/cobol/cobol-accounting-system`.

## 1. Scope of the demo target

The target is intentionally small — this is a feature, not a limitation, for a first
end-to-end proof:

| File | LOC | Role |
|---|---|---|
| `main.cob` | 36 | Menu loop, `ACCEPT`/`DISPLAY`, dispatches to `OperationsProgram` via `CALL ... USING` |
| `operations.cob` | 41 | `CREDIT` / `DEBIT` / `TOTAL` verbs, calls `DataProgram` for persistence |
| `data.cob` | 23 | `READ`/`WRITE` of a single `PIC 9(6)V99` balance, backed by flat working-storage (no VSAM/DB) |

Total ≈ 190 LOC, 3 compilation units, one linear `CALL` graph (`Main → Operations → Data`),
no COPYBOOKs, no file I/O beyond in-memory state re-init per run. This is the correct size
for a pipeline demo: large enough to exercise program-to-program CALL translation, EVALUATE→
switch mapping, PIC-to-decimal typing, and I/O redirection; small enough that a live audience
can read the entire source in the time it takes the agent to plan.

A pre-existing reference port already lives at `cobol-accounting-system/node-accounting-app/`
(`main.js`, `operations.js`, `data.js`, plus Jest tests). This was hand-written (per the repo's
README, via Copilot) prior to any agentic pipeline work here — it is not pipeline output. Its
value for the demo is exactly one thing: it is a second, independently-produced ground truth
for expected CLI behavior, useful for cross-checking the parity harness itself (see §4).

## 2. Migration completeness: recommendation

**Recommend: 100% COBOL → C# for the demo target. Reject hybrid 80/20 for this repo.**

Rationale:

- Hybrid bridging (keep 80% COBOL running, shim 20%) earns its cost on migrations where the
  COBOL estate is large, has external integrations (CICS, VSAM, JCL schedulers) that can't be
  re-hosted in a demo timeframe, or where blast radius of a full cutover is unacceptable. None
  of that applies here: no CICS, no VSAM, no external callers, single process, single terminal
  session. Building bridge infrastructure (a shim process, an IPC contract between COBOL and
  C#, a router) would add machinery whose only job is to prove the concept of bridging —
  machinery this target gives no reason to need.
- The three-program CALL graph is small enough that "hybrid" would mean migrating 2 of 3
  files and leaving one COBOL program in the loop, called from C# via a subprocess or an
  interop shim. That produces a more complex demo (two runtimes, a serialization boundary)
  in exchange for zero additional proof value — full translation already demonstrates
  CALL-graph handling by translating a `CALL` into a C# method invocation.
- The parity gate (§5) needs a single authoritative "before" oracle to diff against. The
  cleanest oracle is the *compiled original COBOL binary*, run as a black box via the same
  CLI transcript replay used to validate the C# build. A hybrid where part of the "before"
  path is already-migrated C# contaminates that oracle.
- 100% migration is achievable inside a demo timeframe (target: single pipeline run, wall
  clock under the time it takes to narrate it — see §6 timing) because of the LOC/complexity
  budget above.

**Fallback if full migration proves infeasible live** (e.g. a code-gen or build failure that
can't be root-caused within the demo window):

1. Ship the two leaf programs fully migrated (`data.cob → Data.cs`, `operations.cob →
   Operations.cs`) and freeze `main.cob` as-is, invoking it as an unmodified COBOL binary via
   `Process.Start` from a thin C# `Program.cs` entry point that owns the menu loop instead.
   This is a *degraded-hybrid* fallback, not the target design — call it out explicitly on
   screen as "fallback path B, not the intended pipeline outcome" so it isn't mistaken for a
   deliberate architecture choice.
2. If even that fails, fall back further to a pre-recorded pipeline run (asciinema cast or
   captured terminal log) of a prior successful full-migration pass, clearly labeled
   "recorded run from <timestamp>, re-run live on request." Never present a recording as live
   without disclosure.
3. `node-accounting-app/` is not an acceptable substitute oracle for the fallback — it is a
   hand-written port, not agent output, and using it in place of C# would misrepresent what
   the pipeline produced. It stays in its existing role (§4) only.

Escalation order during the live demo: attempt full migration → on failure, narrate the
failure honestly and fall to (1) → on further failure, fall to (2). Do not silently downgrade
without telling the viewer which path is showing.

## 3. Target C# architecture

Direct structural translation, one COBOL program → one C# class, preserving the CALL graph
as method calls rather than collapsing to a single Main:

```
CobolAccountingSystem.csproj  (net8.0, console)
├── Program.cs           ← from main.cob:      menu loop, Console.ReadLine/WriteLine
├── OperationsProgram.cs ← from operations.cob: Credit(), Debit(), Total()
├── DataProgram.cs       ← from data.cob:       Read(), Write(), in-memory decimal state
└── CobolAccountingSystem.Tests/
    ├── ParityTests.cs   ← transcript-replay parity harness (§5)
    └── UnitTests.cs     ← per-method tests generated from COBOL PROCEDURE DIVISION paragraphs
```

Typing: `PIC 9(6)V99` → `decimal` (never `double` — decimal PICs must map to exact
fixed-point types; this is a standing project rule, not a demo-specific choice).
`ACCEPT`/`DISPLAY` → `Console.ReadLine()`/`Console.WriteLine()`. `EVALUATE` → `switch`.
`CALL 'X' USING Y` → `new X().Method(y)` or a static call, decided by the agent's translation
skill and visible in the diff — the demo does not hide this decision, it shows the generated
code so the viewer can judge the mapping.

## 4. Role of node-accounting-app during the transition

Kept as a **read-only reference oracle**, never executed as part of the production migration
path, never modified by the pipeline:

- Used once, offline, before the live demo: to cross-validate the parity harness's expected-
  output fixtures. If the COBOL binary and the Node port agree on a transcript, that transcript
  is high-confidence as a fixture; if they disagree, that's a signal the COBOL behavior itself
  is ambiguous (e.g. rounding at a boundary) and needs a human decision before it's baked into
  the parity suite.
- Not shown running live in the main demo flow — it's provenance/validation tooling, not a
  demo character. Mentioning it once during the parity-gate segment ("fixtures cross-checked
  against an independent prior Node port") is sufficient; do not build a three-way bake-off UI
  for it, that's scope the demo doesn't need.

## 5. Parity gate design

Black-box CLI transcript replay, not unit-test-only parity — the thing a viewer needs to see
proven is "same keystrokes in, same screen out," matching how a real user/auditor would judge
equivalence.

**Fixture format** (`parity/fixtures/*.json`), one per scenario:
```json
{
  "name": "credit_then_debit_then_view",
  "inputs": ["2", "250.00", "3", "100.00", "1", "4"],
  "expected_stdout_contains": [
    "Amount credited. New balance: 1250.00",
    "Amount debited. New balance: 1150.00",
    "Current balance: 1150.00",
    "Exiting the program. Goodbye!"
  ]
}
```

Minimum fixture set for the demo (derived from `TESTPLAN.md` if present, else authored from
the three verbs × boundary conditions):
1. View balance only (no mutation) — initial state check.
2. Credit then view — normal path.
3. Debit then view — normal path.
4. Debit exceeding balance — error/edge behavior (must match COBOL's actual behavior,
   including if COBOL has no guard and goes negative — parity means matching *actual* legacy
   behavior, not the "correct" behavior).
5. Invalid menu choice (`5`, non-numeric) — `WHEN OTHER` path.
6. Multiple operations in one session — state persists correctly across the loop.

**Harness** (`parity/run_parity.py` or a C# test runner, either is fine — pick whichever the
pipeline's existing test-generation skill already emits, don't add a new language just for
this):
1. Compile COBOL via GnuCOBOL (`cobc -x main.o operations.o data.o -o accountsystem`) —
   this step must succeed and is itself shown live (§6) as evidence the "before" is real,
   not assumed.
2. Build the generated C# (`dotnet build`).
3. For each fixture: pipe `inputs` as stdin to both the compiled COBOL binary and the C#
   binary; capture stdout; assert both outputs satisfy `expected_stdout_contains` and, for
   the strict mode, assert the two outputs are byte-identical after normalizing line endings.
4. Gate verdict: PASS only if every fixture passes on both binaries. One failing fixture
   blocks the gate — no partial credit, no "mostly passes."

This is the same principle as the project's walk-forward/embargo discipline applied to code
migration: don't crown a migration on a single manually-eyeballed run; crown it on a fixed,
pre-declared fixture set run against both artifacts under identical harness conditions.

## 6. Live demo script

Target total runtime: 6–9 minutes narrated. Every step below is a real command executed on
screen — no step is described without also being shown.

**Step 0 — Setup (10s, can be pre-staged before recording starts)**
Terminal showing `cobol-accounting-system/` tree (`main.cob`, `operations.cob`, `data.cob`).
Narration: "190 lines of COBOL, three programs, one CALL graph. No frameworks, no database —
this is the whole system."

**Step 1 — Show the COBOL running (30s)**
```
$ cobc -x main.cob operations.cob data.cob -o accountsystem
$ ./accountsystem
```
Live keystrokes: view balance → credit 200 → view balance → exit. This transcript becomes
fixture #2/#3 material and establishes ground truth on screen before any migration happens.

**Step 2 — Kickoff command (5s)**
```
$ migrate cobol-accounting-system --target csharp --out ./out/csharp --full
```
(Actual CLI name TBD by the pipeline's harness design — this doc treats it as a black box
entry point; wire the real command name when the harness from `design/02-*` is implemented.)

**Step 3 — Live progress (60–90s)**
Streamed agent output, phase-labeled, matching the pipeline's actual phase names (parse →
plan → generate → build → test → parity). Viewer should see, per COBOL file, which C# file
is being generated, and a running pass/fail count for generated unit tests as they're created.
This is the moment that sells "agentic," not scripted templating — the log must show real
tool calls (read `operations.cob`, write `OperationsProgram.cs`, run `dotnet build`), not a
progress bar with no substance behind it.

**Step 4 — Generated C# files (30s)**
```
$ tree out/csharp
$ bat out/csharp/OperationsProgram.cs
```
Side-by-side (COBOL PROCEDURE DIVISION paragraph vs. generated C# method) for one paragraph,
e.g. the CREDIT verb, to make the translation legible in real time.

**Step 5 — Unit test results (20s)**
```
$ dotnet test out/csharp/CobolAccountingSystem.Tests
```
Show pass count; these are generated-from-COBOL-logic unit tests (§3), distinct from the
parity harness — this step proves the C# is internally correct, §6 proves it's *equivalent*.

**Step 6 — Parity gate (60–90s, the climax)**
```
$ python parity/run_parity.py --cobol-bin ./accountsystem --csharp-bin out/csharp/bin/... 
```
Show the fixture list scrolling with PASS/FAIL per fixture, then the final gate verdict line,
e.g. `PARITY GATE: PASS (6/6 fixtures, byte-identical stdout)`. If any fixture fails, the
script must stop and show the actual diff (COBOL line vs C# line) — never hide a failure
behind a summary.

**Step 7 — Final running C# app (30–45s)**
```
$ dotnet out/csharp/bin/Release/net8.0/CobolAccountingSystem.dll
```
Re-run the *exact same keystrokes* from Step 1 (view → credit 200 → view → exit) live, and
let the viewer visually compare the transcript to Step 1's. This closing beat is the payoff:
same input, same output, different runtime, and the viewer watched both.

**Closing card (10s)**: LOC migrated, fixtures passed, wall-clock time for Steps 2–6, link to
generated diff. State plainly whether this was a live run or (per §2 fallback path 2) a
recorded run — never let ambiguity stand.

## 7. What this demo does not attempt

Explicitly out of scope, to keep the demo honest about its size:
- No CICS/JCL/VSAM — target has none.
- No multi-module hybrid runtime — see §2 rejection of hybrid.
- No performance benchmarking — a 190-LOC console app has nothing meaningful to benchmark.
- No claim of generalization to large COBOL estates from this one result — this is a
  smallest-viable proof of the pipeline mechanics (parse → generate → test → parity-gate),
  not evidence the same pipeline scales unmodified to a 500k-LOC mainframe system. State that
  boundary out loud if asked.
