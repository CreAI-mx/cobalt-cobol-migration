# 03 — Skills Catalog for the COBOL → C# Migration Pipeline

Status: DRAFT. Depends on `02-harness-orchestration.md` (not yet present in this
repo at time of writing). Where harness primitives are referenced below
(orchestrator loop, phase gate, artifact bus, run ledger) this doc assumes the
conventional Claude Code skills-plugin shape — `.claude/skills/<name>/SKILL.md`
with YAML frontmatter (`name`, `description`, trigger phrases) plus optional
`scripts/`, `references/` — and a harness that invokes skills as discrete,
checkpointed phases over a shared on-disk run directory. Reconcile skill I/O
paths against the harness doc once it exists; the contract described here
(run directory layout, artifact bus, gate protocol) is the assumption to
validate, not a decree.

Target repo for the demo pipeline: `/home/frg/creai/cobol/cobol-accounting-system`
(COBOL: `main.cob`, `operations.cob`, `data.cob`; existing partial rewrite in
`node-accounting-app/`; `TESTPLAN.md` as a hand-written oracle of expected
behavior — treat it as ground truth for parity validation, not as a skill
input to regenerate).

## 0. Shared conventions

**Run directory.** Every pipeline run gets `runs/<run_id>/` under the repo
root (or a configured workspace root for larger portfolios). All skills read
prior-phase artifacts from there and write their own outputs there — this is
the "artifact bus." No skill talks to another skill directly; they compose
only through files in this directory plus a `run_ledger.json` that the
harness updates after each phase gate.

```
runs/<run_id>/
  00-discovery/           inventory.json, entry_points.json, risk_notes.md
  01-structural/          ast/*.json, cfg/*.json, copybook_index.json, paragraph_graph.json
  02-business-logic/      rules/*.md, rules/*.yaml, decision_tables/*.csv
  03-dependency-map/      dep_graph.json, call_graph.dot, data_flow.json
  04-conversion/          csharp/**/*.cs, conversion_manifest.json
  05-test-generation/     tests/**/*.cs, fixtures/**, coverage_targets.json
  06-parity-validation/   parity_report.json, divergences/*.json
  07-bugfix-loop/         patches/*.diff, fix_log.jsonl
  08-cost-governance/     cost_ledger.jsonl, budget_status.json
  09-doc-generation/      docs/**/*.md, traceability_matrix.csv
  run_ledger.json
```

**Phase gate contract.** Each skill, on completion, writes a `_gate.json` in
its own output directory: `{status: pass|fail|needs_review, summary, metrics,
next_recommended_skill}`. The harness orchestrator reads this to decide
whether to advance, retry, or escalate to a human checkpoint. A skill must
never silently degrade scope (e.g., skip a COBOL paragraph) without recording
it in `risk_notes.md` / the equivalent phase note — downstream skills key off
these notes to know what's unverified.

**Idempotency.** Every skill must be safe to re-run against the same
`run_id` (e.g., after a partial failure or a cost-governance pause) —
outputs are content-addressed or overwritten wholesale, never appended
ambiguously, so a retry doesn't fork into two conflicting states.

**Tool access.** All skills default to read-only tools over `cobol-*` source
trees (Read/Grep/Glob) plus Bash restricted to declared allowlists (compilers,
linters, `dotnet test`, `cobc`, static analyzers). Only the conversion,
test-generation, bug-fix, and doc-generation skills get Write/Edit, and only
scoped to their own `runs/<run_id>/...` output subtree plus the target C#
project directory — never the original COBOL sources, which stay
read-only for the life of the run (they're the oracle).

---

## 1. `cobol-discovery`

**Trigger.** Start of a new migration run; user says "migrate <repo>",
"scope this COBOL codebase", or harness auto-invokes as phase 0 for any run
with no `00-discovery/` artifacts yet.

**Inputs.** Repo root path. Optional scope filter (subdirectory, program
name allowlist). Nothing from prior phases (this is phase 0).

**Outputs** (`runs/<id>/00-discovery/`):
- `inventory.json` — every `.cob`/`.cpy`/`.cbl`/JCL file, size, last-modified,
  detected dialect (GnuCOBOL, IBM Enterprise, Micro Focus — dialect drives
  which parser the structural-analysis skill selects).
- `entry_points.json` — PROCEDURE DIVISION entry paragraphs, called
  programs, any embedded SQL/CICS/JCL triggers.
- `risk_notes.md` — anything non-standard: dynamic CALLs, ALTER statements,
  self-modifying GO TO, copybook macros with conditional compilation.
- `_gate.json`.

**Tools.** Read, Grep, Glob, Bash (restricted to `find`, `wc`, `file`,
checksum utilities — no compilation yet).

**Composition with harness.** Pure phase-0 producer; no upstream dependency.
Gate criterion: `inventory.json` must account for 100% of `*.cob`/`*.cpy`
files found by Glob — a mismatch is a hard fail, not a warning, since every
downstream skill assumes discovery is exhaustive. On the demo repo this
should immediately flag `node-accounting-app/` as a **pre-existing partial
target** rather than a COBOL source — discovery must classify it out of
scope and note it in `risk_notes.md` so structural-analysis doesn't try to
parse JS as COBOL.

---

## 2. `cobol-structural-analysis`

**Trigger.** `00-discovery/_gate.json.status == pass`. Also re-triggerable
standalone for "re-parse just this program" during the bug-fix loop if a
divergence is traced to a parser miss.

**Inputs.** `00-discovery/inventory.json`, `entry_points.json`. Direct read
access to the COBOL source files named there.

**Outputs** (`runs/<id>/01-structural/`):
- `ast/<program>.json` — per-program AST (DIVISION/SECTION/PARAGRAPH tree,
  DATA DIVISION layout with PIC clauses, REDEFINES, OCCURS).
- `cfg/<program>.json` — control-flow graph at paragraph granularity
  (PERFORM chains, GO TO targets, fall-through order — COBOL has no block
  scoping, so this graph is the load-bearing artifact for later semantic
  work).
- `copybook_index.json` — resolved COPY/REPLACING expansions, so later
  skills don't re-resolve copybooks independently and risk divergent
  expansions.
- `paragraph_graph.json` — every paragraph, its PERFORM callers/callees, and
  whether it's PERFORMed THRU a range (a common source of subtle bugs when
  the migration flattens paragraph ranges into methods).
- `_gate.json` with a `parse_coverage` metric (% of statements the parser
  classified with high confidence vs. flagged `UNPARSED`).

**Tools.** Read, Grep, Glob, Bash (invoking a COBOL parser — e.g. GnuCOBOL's
`cobc -fsyntax-only`, or a dedicated COBOL AST library/CLI declared as a
project dependency; this skill should defer parser choice to whatever
`r8-cobol-parsers` workstream lands on, treating it as a pluggable backend
behind a stable JSON schema).

**Composition.** Gate: `parse_coverage >= 0.98` to auto-advance; below that,
harness routes to a human-review checkpoint rather than silently feeding a
partial CFG into business-logic extraction (a missed GO TO target corrupts
every downstream rule inference). On the demo repo (~3 small `.cob` files)
expect near-100% coverage — this skill's real value shows up on larger
portfolios, so keep the confidence-threshold logic even though the demo
won't exercise it.

---

## 3. `cobol-business-logic-extraction`

**Trigger.** `01-structural/_gate.json.status == pass`.

**Inputs.** `ast/*.json`, `cfg/*.json`, `paragraph_graph.json`. Also reads
raw source for comment blocks (COBOL comments often carry business intent
the AST discards).

**Outputs** (`runs/<id>/02-business-logic/`):
- `rules/<program>.md` — human-readable business rule descriptions per
  paragraph cluster (e.g., "interest accrual: if balance > threshold, apply
  tiered rate from table X").
- `rules/<program>.yaml` — the same rules in a structured schema (condition,
  action, source paragraph refs, confidence) that the conversion and
  test-generation skills consume mechanically rather than re-reading prose.
- `decision_tables/*.csv` — extracted EVALUATE/nested-IF decision tables,
  since these map most directly to C# switch expressions or rules-engine
  tables and are worth keeping tabular rather than prose.
- `_gate.json` with `rules_confidence` (LLM self-rated, cross-checked against
  a paragraph-coverage count: every paragraph in `paragraph_graph.json`
  should be referenced by at least one rule or explicitly marked
  `no-business-logic` — e.g., pure I/O boilerplate).

**Tools.** Read only over structural artifacts + raw source. No Bash needed
beyond diffing/coverage scripts. This is the skill most likely to
hallucinate intent from ambiguous COBOL — pair with `ml-science-protocol`-style
verify-before-assert discipline: every extracted rule must cite the
paragraph name and line range it came from, no rule without provenance.

**Composition.** Feeds both `dependency-mapping` (shares the paragraph graph
lineage) and directly downstream into `code-conversion` and
`test-generation`. This is the one skill whose output a human domain
reviewer should skim before conversion starts on anything beyond a toy
repo — flag in `_gate.json` as `needs_review` by default unless the harness
config explicitly sets an auto-advance flag for demo/CI runs.

---

## 4. `cobol-dependency-mapping`

**Trigger.** Can run in parallel with business-logic-extraction (both only
need phase-01 structural artifacts) — harness should fan these out
concurrently rather than serialize them.

**Inputs.** `ast/*.json`, `entry_points.json`, `copybook_index.json`, plus
discovery's `inventory.json` for file-level CALL resolution (static CALL
'PROGRAM-NAME' vs. dynamic CALL identifier).

**Outputs** (`runs/<id>/03-dependency-map/`):
- `dep_graph.json` — program-to-program CALL graph, copybook fan-in
  (which programs share `data.cob`-style copybooks — on the demo repo this
  is exactly the `main.cob` → `operations.cob`/`data.cob` relationship),
  and external I/O touchpoints (files, JCL-invoked datasets, any embedded
  SQL).
- `call_graph.dot` — Graphviz rendering for human review/docs.
- `data_flow.json` — record-level lineage: which fields in `data.cob`'s
  layouts are read/written by which paragraphs in `operations.cob` — this is
  the artifact that determines safe conversion *order* (leaf programs with
  no outstanding dependencies convert first).
- `_gate.json` with a cycle-detection flag — COBOL CALL graphs can be
  recursive/cyclic in ways that complicate a bottom-up conversion order; a
  detected cycle should be surfaced, not silently broken.

**Tools.** Read, Bash (Graphviz `dot` for rendering only — no source
mutation).

**Composition.** Its primary consumer is the harness's *scheduler*, not
another skill directly: `conversion_manifest.json` (produced downstream by
`code-conversion`) should be seeded from this skill's topological order.
Also consumed by `cost-governance` for estimating per-program conversion
cost by dependency-cluster size.

---

## 5. `cobol-to-csharp-conversion`

**Trigger.** `02-business-logic` and `03-dependency-map` both gated pass. If
`business-logic-extraction` is `needs_review`, harness should hold this
skill at a checkpoint rather than auto-advance — converting against
unreviewed rule extraction risks compounding a misread business rule into
shipped C#.

**Inputs.** `rules/*.yaml`, `decision_tables/*.csv`, `dep_graph.json`,
`data_flow.json`, `ast/*.json` (for exact PIC-clause → C# type mapping —
COBOL COMP-3/PACKED-DECIMAL numeric precision must map to `decimal`, not
`double`, to avoid silent rounding drift versus the original).

**Outputs** (`runs/<id>/04-conversion/`):
- `csharp/**/*.cs` — generated project, one class per COBOL program (or per
  logical module for larger PERFORMed structures), following whatever target
  project layout the harness's architecture doc (`01-architecture` or
  similar) specifies — if none exists yet, default to a plain layered
  console-app/class-library split (`Domain/`, `Application/`, `Data/`) so the
  demo repo's `main.cob`/`operations.cob`/`data.cob` split maps to
  `Program.cs` / `AccountingOperations.cs` / `AccountRecord.cs`-style types.
- `conversion_manifest.json` — per-program: source file, converted file(s),
  rule IDs applied, PIC→type mapping table used, any TODO markers for
  unsupported constructs (e.g., ALTER, SORT verb edge cases).
- `_gate.json` with `build_status` (must actually compile — this skill owns
  running `dotnet build` before declaring pass, not just emitting text).

**Tools.** Read (all upstream artifacts + COBOL source for final
double-check), Write/Edit (scoped to the target C# project path only), Bash
(`dotnet build`, `dotnet format`).

**Composition.** This is the skill most tightly coupled to whatever
harness "workspace" convention 02-harness-orchestration.md defines for
where generated code lands — needs that doc to pin down whether conversion
writes into the same repo (a new `csharp/` sibling to `cobol-accounting-system/`)
or a separate output repo. Until resolved, default assumption: sibling
directory `cobol-accounting-system-csharp/` outside the COBOL tree, so the
COBOL source stays untouched and diffable against `TESTPLAN.md`.

---

## 6. `csharp-test-generation`

**Trigger.** `04-conversion/_gate.json.build_status == pass`.

**Inputs.** `conversion_manifest.json`, `rules/*.yaml`, `decision_tables/*.csv`
(decision tables are the most direct source of test-case rows — each row is
a candidate unit test), and the repo's existing `TESTPLAN.md` if present —
treat hand-written test plans as a required source, not optional context,
since they encode human-verified expected behavior for this exact program.

**Outputs** (`runs/<id>/05-test-generation/`):
- `tests/**/*.cs` — xUnit/NUnit test project mirroring `csharp/`.
- `fixtures/**` — golden input/output fixtures, ideally derived by *running
  the original COBOL* (via GnuCOBOL) on generated inputs and capturing
  output as the oracle, rather than trusting the LLM's guess at expected
  output — this is the load-bearing move that makes parity validation
  meaningful rather than circular.
- `coverage_targets.json` — mapping from decision-table rows / TESTPLAN.md
  line items to generated test names, so gaps are visible.
- `_gate.json` with `coverage_pct` against `coverage_targets.json` (target
  100% of TESTPLAN.md items covered by at least one generated test; below
  threshold routes to `needs_review`, not silent pass).

**Tools.** Read, Write/Edit (test project only), Bash (`cobc` to compile and
run the original COBOL for oracle generation, `dotnet test` to confirm
generated tests at least execute — not yet asserting pass, just that they
run — real pass/fail assertion is `parity-validation`'s job).

**Composition.** Depends on GnuCOBOL (or equivalent) being invocable in the
harness sandbox to generate oracles — flag this as an environment
precondition the harness must guarantee (`r8-cobol-parsers` / build-tooling
workstream's concern) rather than something this skill silently falls back
from.

---

## 7. `parity-validation`

**Trigger.** `05-test-generation/_gate.json.status == pass` (tests exist and
run). This is the phase that actually asserts correctness.

**Inputs.** `fixtures/**` (COBOL-derived oracles), `tests/**/*.cs`,
`csharp/**/*.cs`, `dep_graph.json` (to attribute a divergence to the
responsible program/paragraph rather than just "test N failed").

**Outputs** (`runs/<id>/06-parity-validation/`):
- `parity_report.json` — per test: pass/fail, expected vs actual, and (on
  fail) a pointer into `divergences/`.
- `divergences/<test_id>.json` — structured diff: which field, expected
  COBOL value, actual C# value, and a first-pass hypothesis (rounding rule
  mismatch, PIC clause overflow, off-by-one in a PERFORM VARYING → for-loop
  translation — the most common conversion bug class).
- `_gate.json` with `parity_rate` (fraction passing) — this is the primary
  crown metric for the whole pipeline; report it the way
  `ml-science-protocol` wants numeric claims reported: with N (test count),
  not just a percentage.

**Tools.** Read, Bash (`dotnet test` with structured output, e.g. TRX/JSON
logger — parse machine-readable results, don't scrape console text).

**Composition.** `parity_rate < 1.0` routes to `bug-fix-loop`, not back to
`code-conversion` from scratch — re-conversion from scratch on every
mismatch is the expensive/unstable path; targeted patching is preferred and
is exactly `bug-fix-loop`'s job. `parity_rate == 1.0` with N below some
minimum (e.g., a program with zero decision-table rows produced zero tests)
should still route to `needs_review` — 100% of zero tests is not evidence.

---

## 8. `bugfix-loop`

**Trigger.** `06-parity-validation/_gate.json.parity_rate < threshold` (harness-
configured, e.g. 1.0 for financial code, no partial credit).

**Inputs.** `divergences/*.json`, the specific `csharp/*.cs` file(s)
implicated, the original COBOL paragraph(s) named in `divergences` for
re-reference, `cost_ledger.jsonl` (to respect a per-run fix-attempt budget —
this loop must not be unbounded).

**Outputs** (`runs/<id>/07-bugfix-loop/`):
- `patches/*.diff` — one patch per fix attempt, applied directly to
  `csharp/**/*.cs`.
- `fix_log.jsonl` — append-only: attempt N, divergence targeted, hypothesis,
  patch applied, re-test result. This is the audit trail that lets a human
  reviewer see *why* the final code looks the way it does, not just that it
  passes.
- `_gate.json` — loop terminates on `parity_rate == threshold` (success),
  `attempts >= max_attempts` (escalate to human, do not keep spending), or
  `cost-governance` signaling budget exhaustion (below).

**Tools.** Read, Edit (C# files only — never touches COBOL source or the
oracle fixtures, which stay the fixed ground truth), Bash (`dotnet test`
re-run after each patch, scoped to just the affected test(s) first for speed,
full suite before declaring the loop-level gate pass to catch regressions).

**Composition.** This is the one skill that loops on itself — internally it
re-invokes `parity-validation`'s test-execution step (not the whole skill,
just the `dotnet test` + report step) after each patch, rather than routing
back through the harness's phase graph each iteration, since that would be
prohibitively slow for a tight edit-test cycle. It reports back to the
harness as a single phase whose `_gate.json` reflects the end state, with
`fix_log.jsonl` as the detailed trace.

---

## 9. `migration-cost-governance`

**Trigger.** Not a discrete pipeline phase — a cross-cutting skill invoked
by the harness before and after every other phase (pre-flight cost estimate,
post-hoc actual-cost recording), and directly by the user for "what has this
run cost so far" / "will this program be worth converting" queries.

**Inputs.** `run_ledger.json` (which phases have run), token/cost telemetry
the harness exposes per skill invocation, `dep_graph.json` (cluster size
estimates cost of converting a whole dependency cluster atomically),
`inventory.json` (program count/size as the base cost driver).

**Outputs** (`runs/<id>/08-cost-governance/`):
- `cost_ledger.jsonl` — append-only, one row per skill invocation: phase,
  tokens in/out, wall time, model used, estimated $ cost.
- `budget_status.json` — running total vs. configured run budget, plus a
  per-phase forecast for remaining work (extrapolated from cost-per-program-
  so-far on this run).
- `_gate.json` — not pass/fail in the usual sense; instead emits
  `continue | pause_for_approval | hard_stop` which the harness orchestrator
  must check before dispatching the *next* phase, not just at run start.

**Tools.** Read (ledger + telemetry only), Bash (arithmetic/aggregation
scripts) — no source access at all, this skill only touches its own
bookkeeping files.

**Composition.** This is the skill most dependent on what
`02-harness-orchestration.md` defines for how per-tool-call cost is exposed
to skills (if the harness doesn't surface token telemetry per invocation,
this skill degrades to program-count-based estimation only, which is much
weaker). Flag as a resolve-before-implementation item against that doc.
Reasonable default thresholds for a demo-sized repo: warn at 80% of budget,
hard-stop at 100%, always allow a human override to raise budget and resume
rather than restart the run.

---

## 10. `migration-doc-generation`

**Trigger.** `06-parity-validation` (or `07-bugfix-loop`) reaches a final
`parity_rate` the harness accepts as run-complete — this is the last phase,
run once per completed run (and re-runnable standalone if only docs need
refreshing after a manual post-hoc patch).

**Inputs.** Every prior phase's artifacts: `inventory.json`, `rules/*.yaml`,
`dep_graph.json`, `conversion_manifest.json`, `parity_report.json`,
`fix_log.jsonl`, `cost_ledger.jsonl`.

**Outputs** (`runs/<id>/09-doc-generation/` and the target C# tree):
- `README.md` (solution root) — human operator: what it is, how to build/run. No module internals.
- `docs/DOCUMENTATION.md` — Documentation Master for coding agents: one row per module and submodule, relative links, "read when". Index only — never the body.
- `src/{Sln}.{Layer}/README.md` and `UseCases/{Behavior}/README.md` — leaf docs next to code so an agent opens one file without ingesting siblings.
- `docs/ARCHITECTURE.md`, `docs/ONBOARDING.md`, `docs/CONVERSION-NOTES.md`.
- `docs/source/*` — carried COBOL-era markdown, never overwritten.
- `docs/runs/{run_id}.md` — files migrated, parity, coverage, cost.
- `traceability_matrix.csv` — row per COBOL paragraph: source location,
  extracted rule ID, target C# method, covering test(s), parity status. This
  is the compliance/audit artifact for regulated environments (accounting
  code plausibly needs one).
- `_gate.json`.

**Tools.** Read (all artifacts), Write (docs directory only).

**Composition.** Purely a synthesis skill — no Bash beyond markdown/CSV
formatting scripts. Its main harness dependency is where generated docs live
relative to the target C# project (`docs/` inside the new project vs. back
into `runs/<id>/` only) — again pin down against `02-harness-orchestration.md`
once available; default to writing into the target C# project's `docs/` so
they ship with the code, plus keeping the `runs/<id>/09-doc-generation/`
copy as the run-audit record.

---

## Open items to reconcile against `02-harness-orchestration.md`

1. Exact phase-gate JSON schema (field names above are illustrative).
2. Where generated C# code lives relative to the COBOL source repo.
3. Whether cost telemetry is harness-native (preferred) or must be
   self-tracked per skill via wrapped Bash calls.
4. Parser backend selection for `cobol-structural-analysis` — pending
   `r8-cobol-parsers` workstream output.
5. Concurrency contract — can `business-logic-extraction` and
   `dependency-mapping` actually be dispatched in parallel by the harness,
   or does the orchestrator only support strictly sequential phases today.
</content>
