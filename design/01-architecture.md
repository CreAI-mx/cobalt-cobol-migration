# 01 — Architecture: Agentic COBOL-to-C# Migration Platform

Status: draft v1. Author: platform design (agent-generated). Scope: system architecture only — orchestration internals live in `02-harness-orchestration.md`, agent capabilities in `03-skills.md`, the concrete migration pipeline in `04-pipeline-steps.md`.

## 1. Problem framing

Demo repo: `/home/frg/creai/cobol/cobol-accounting-system` — 3 COBOL programs (`main.cob`, `operations.cob`, `data.cob`, ~100 LOC total), CALL-linked, in-memory balance state (no VSAM/DB, no JCL, no CICS). A `node-accounting-app/` already exists as a prior hand/Copilot port — it is **reference material and an oracle for behavioral parity**, not itself the migration target.

The platform must demo credibly at this scale while the architecture generalizes to real enterprise COBOL: multi-million-LOC estates, VSAM/DB2 data stores, CICS transactions, JCL batch orchestration, copybooks shared across hundreds of programs. Design decisions below are made against the enterprise case first, then shown to collapse cleanly onto the toy repo — not the reverse — because the inverse (demo-first design) is what produces platforms that can't survive contact with a real COBOL estate.

## 2. Target shape: modular monolith, not microservices, not a single flat project

**Decision: a modular .NET monolith** (single deployable per bounded migration unit, internally decomposed into projects by COBOL program/module boundary), not a microservices mesh, and not a single undifferentiated C# project.

Rationale:
- Real COBOL programs already encode a call graph (`CALL 'X' USING ...`) that *is* a module boundary the business has lived with for decades. Preserving that boundary as C# project/namespace boundaries (`Main`, `Operations`, `Data` → `AccountingSystem.Cli`, `AccountingSystem.Operations`, `AccountingSystem.DataAccess`) keeps the migration diff-reviewable against the source: a COBOL reviewer can map `PERFORM`/`CALL` to a C# method call 1:1.
- Microservices impose network boundaries and independent deployability where the source system has neither — COBOL programs share process memory and a WORKING-STORAGE lifetime. Turning `CALL 'DataProgram'` into an HTTP call across services introduces a distributed-systems failure mode (partial failure, latency, serialization drift) that does not exist in the original and that the enterprise almost never asked for. Splitting into services is a *later*, separately justified decision (e.g., when a subsystem needs independent scaling or ownership by a different team) — not a default imposed by the migration tool.
- A flat single-project translation (one `Program.cs` with everything inlined) fails the enterprise case immediately: it doesn't scale past a handful of programs, loses the module boundary that makes partial migration and partial rollback possible, and makes it impossible to unit-test one COBOL-program-equivalent in isolation.

Concretely, for the demo repo:
```
AccountingSystem.sln
├── src/AccountingSystem.Domain/       # POCOs: Account, Money (decimal-backed, COBOL PIC 9(7)V99 semantics)
├── src/AccountingSystem.Operations/   # credit/debit/view-balance business rules  ← ex operations.cob
├── src/AccountingSystem.DataAccess/   # IAccountStore + persistence impl          ← ex data.cob
├── src/AccountingSystem.Cli/          # menu loop, DI composition root            ← ex main.cob
└── tests/*.Tests/                     # one test project per source project
```
This shape scales to enterprise by adding sibling project groups per COBOL "system" (e.g., `Billing.*`, `Ledger.*`), each internally following the same program→project mapping, with shared copybook-derived types promoted to a common `*.Contracts` project. A monolith stays viable up to the point a subsystem needs independent lifecycle — the modular boundary is exactly what makes extracting it into a separate service later a mechanical, low-risk operation instead of a rewrite.

## 3. Determinism vs. LLM agency — the central design axis

This is the load-bearing decision of the whole platform: **anything that must be provably correct is deterministic tooling; anything that requires judgment, disambiguation, or synthesis is an LLM agent — and the boundary is drawn so that agent output is always independently checked by a deterministic gate before it is trusted.**

### 3.1 Deterministic zone (no LLM in the loop, or LLM output treated as untrusted draft)

| Concern | Mechanism |
|---|---|
| COBOL structural parsing (DIVISIONs, PARAGRAPHs, PIC clauses, COPY expansion, CALL graph) | A real COBOL parser (see `03-skills.md` / `r8-cobol-parsers` track — e.g. GnuCOBOL AST, ANTLR COBOL grammar, or `cobol85` tree-sitter grammar), never an LLM guessing structure from text. |
| Numeric semantics (`PIC 9(7)V99`, `COMP-3`, rounding, `ON SIZE ERROR`) | Deterministic decimal-mapping rules encoded as a lookup table + codegen, not LLM arithmetic reasoning. |
| Call-graph → module-boundary mapping | Deterministic graph extraction from the parse tree. |
| Compilation of generated C# | `dotnet build`, deterministic, pass/fail. |
| Unit test generation *execution* and pass/fail | `dotnet test`, deterministic. |
| Parity check (COBOL output vs C# output over the same inputs) | Deterministic diff on a golden-output harness (`06-parity-testing.md`), driving both the compiled COBOL binary and the C# binary with identical stdin scripts. |
| Build/deploy gating | CI pipeline, deterministic pass/fail gates (`09-cicd-gating` track). |
| Progress/state tracking of the migration (what's done, what's pending, what regressed) | A structured state store (see `09-observability-progress.md`), not an agent's self-report. |

### 3.2 Agentic zone (LLM judgment required)

| Concern | Why it needs an agent |
|---|---|
| Semantic intent extraction from PARAGRAPH names, comments, and business logic idioms | No parser recovers "why" from COBOL; this requires reading `PERFORM` bodies and inferring intent (e.g. is this validation, a business rule, or an artifact of 1980s memory constraints?). |
| Idiomatic C# code synthesis from the deterministic IR | Translating a parsed COBOL paragraph into idiomatic, reviewable C# (naming, exception vs. return-code style, async where appropriate) is a generation task, not a rule table — COBOL has no 1:1 grammar mapping to C#. |
| Copybook/data-structure → C# type/record synthesis, including nullable/Optional decisions | Requires judgment about what an 88-level condition-name really models. |
| Explaining a parity mismatch and proposing a fix | Root-causing "why did output diverge on this input" from a diff plus source context is exactly the reasoning task LLMs are suited for; the diff itself is deterministic. |
| Bug triage and fix proposals (`08-bug-resolution.md`) | Same pattern: deterministic detection, agentic diagnosis and patch proposal. |
| Human-readable migration reports / dashboard narrative | Summarization is agentic; the underlying metrics it summarizes are deterministic. |

### 3.3 The governing rule

**Every agent output that claims a fact about correctness must be re-verified by a deterministic check before that fact is allowed to affect platform state.** An agent may *propose* "this C# method is behaviorally equivalent to `2100-CREDIT-ACCOUNT`," but the platform only records equivalence after the parity harness has run identical inputs through both and diffed the outputs byte-for-byte (`06-parity-testing.md`). This mirrors the `ml-science-protocol` verify-before-assert stance already standing for this operator: LLM self-report is a hypothesis, never a result. No dashboard status, no "migration complete" flag, no commit gate is driven by an agent's claim alone.

## 4. Deployment topology

Three concentric rings, so the same architecture serves a laptop demo and a production estate without a redesign:

**Ring 0 — local/dev (the demo default).**
- Claude Code (or the chosen harness — see `02-harness-orchestration.md`) running locally against the repo checkout.
- GnuCOBOL installed locally to compile/run the source COBOL as the parity oracle.
- .NET SDK locally to build/run the generated C#.
- SQLite (or even a JSON file, matching `data.cob`'s triviality) as the account-balance store — deliberately not overbuilt for a 3-program demo.
- Single-machine, single-process orchestration; no queue, no distributed workers.

**Ring 1 — CI/shared team environment.**
- The same pipeline steps (`04-pipeline-steps.md`) run inside containers in GitHub Actions/equivalent: a COBOL-compiler container (GnuCOBOL) + a .NET SDK container, both pinned by digest for reproducibility.
- Parity and unit test results, plus progress state, are pushed to a shared store (e.g., a Postgres instance or the codebase-memory graph already in use in this environment) so the dashboard (`10-dashboard-ui.md`) reflects team-wide, not per-laptop, state.
- Agent calls (LLM invocations) are metered and logged here for cost governance (`05-cost-governance` track) — every agent turn in Ring 1 is attributable to a pipeline run ID.

**Ring 2 — production/enterprise scale.**
- Containerized workers (Kubernetes Jobs or equivalent), each processing one migration unit (one COBOL program group) per pod, horizontally parallel across the estate — the modular-monolith boundary from §2 is exactly the unit of parallel migration work.
- A durable job queue (migration units, parity runs, bug-fix cycles) decouples agent latency/cost from pipeline throughput; agents run as bounded, retryable, checkpointed tasks, never as long-lived stateful processes holding pipeline state in memory.
- The deterministic zone (§3.1) runs as stateless, horizontally scaled workers; the agentic zone runs behind a rate-limited/cost-governed gateway so a runaway agent loop cannot silently burn budget across thousands of programs — this is the direct scale-up of the Ring-1 metering.
- Generated C# artifacts land in the *same* modular-monolith shape per subsystem as §2, assembled by a deterministic aggregation step (not an agent) that merges per-unit outputs into the target solution tree and resolves cross-unit references (shared copybook types) via the `*.Contracts` projects.
- Human-in-the-loop gate before any generated subsystem is promoted from "parity-passing" to "candidate for cutover" — this is a governance decision, kept explicitly out of agent hands regardless of how confident the agent chain is.

The three rings are the same pipeline at increasing concurrency and increasing formality of the trust boundary — Ring 0 is Ring 2 with N=1 and no queue, which is why the demo is representative rather than a toy that gets thrown away.

## 5. Scaling from 3-program demo to enterprise COBOL

The demo repo has none of the following, and the architecture must not implicitly assume their absence:

| Enterprise reality | Demo repo | Design accommodation |
|---|---|---|
| VSAM/DB2/IMS data stores | in-memory balance via `data.cob` | `IAccountStore` abstraction from day one (already required even for the demo) — swapping SQLite for a DB2-backed adapter is a new implementation of an existing interface, not a redesign. |
| CICS transactions | none (batch/interactive CLI) | Out of scope for this platform version; flagged as a future ring — CICS transaction boundaries would map to a transactional-unit-of-work abstraction analogous to `IAccountStore`, but is not built until a real CICS estate is in scope. |
| JCL batch orchestration | none | The pipeline's "migration unit" concept (§4, Ring 2) is designed to also represent a JCL step later, without renaming the abstraction. |
| Shared copybooks across hundreds of programs | none (each `.cob` is self-contained) | `*.Contracts` project pattern (§2) exists in the architecture now, even though the demo doesn't strictly need it, specifically so the enterprise case doesn't require inventing it under pressure later. |
| Thousands of programs, millions of LOC | 3 programs, ~100 LOC | Ring 2 job-queue parallelism (§4) is the only way this is tractable; the per-program unit of work is fixed from the demo (§2's project-per-COBOL-program mapping) so scaling is a matter of running more units concurrently, not restructuring the unit itself. |
| Regression risk on production financial systems | none (toy balance) | Parity testing (`06-parity-testing.md`) as a hard gate, human promotion gate (§4 Ring 2) before cutover — these exist in the design now precisely because retrofitting a safety gate after a demo-only mentality ships is how migrations cause real financial-system incidents. |

The single sentence version: **the demo is architected as "enterprise architecture at N=3,"** not as a bespoke toy that later needs replacing — every ring, gate, and abstraction introduced for the 3-program repo is the smallest version of the same mechanism the enterprise case needs, never a shortcut that a real estate would outgrow.

## 6. The ratio question: 100% COBOL migration vs. 80/20 hybrid bridge

**Recommendation: 100% COBOL-to-C# migration for the demo scope, not a hybrid Node bridge — with the existing `node-accounting-app/` retained solely as a parity oracle, not as part of the delivered architecture.**

Reasoning:

1. **What "hybrid 80/20" would actually buy here, and what it costs.** A hybrid bridge earns its complexity in a real enterprise migration when large COBOL subsystems (e.g., untouched batch settlement jobs) are too risky or too low-value to migrate immediately, and a thin interop layer (message queue, shared file, REST façade) lets migrated and unmigrated subsystems coexist during a multi-year transition. That justification requires scale and heterogeneous risk profiles across subsystems. At 3 programs and ~100 LOC with no external integrations, there is no subsystem large or risky enough to justify carrying a second production language and a bridge/interop layer — the "20% kept as Node" would not correspond to any real risk boundary, it would just be scope arbitrarily left undone, and it would double the platform's demo-time complexity (must now demonstrate C#-Node interop, not just COBOL-C# parity) for zero architectural lesson gained.
2. **What the demo needs to prove.** The value proposition of this platform is "agentic pipeline takes COBOL in, produces verified, idiomatic C# out, with provable parity" — a 100% migration is the only version of the demo that proves the full pipeline end-to-end (parse → synthesize → unit test → parity test → gate → deploy). A hybrid demo would prove a weaker claim (agent can migrate *most* of a trivial program) while adding an unrelated capability (bridge/interop) that isn't the platform's differentiator.
3. **Where the existing Node app fits instead.** `node-accounting-app/` is valuable as a second independent implementation of the same behavior, useful as an additional parity oracle/cross-check alongside the compiled COBOL binary in `06-parity-testing.md` (three-way diff: COBOL output vs. Node output vs. new C# output on identical input scripts) — this raises confidence in the parity harness itself (if COBOL and Node already agree, and C# then also agrees, that's stronger evidence than a two-way check). It is not, however, load-bearing production code in the target architecture, and no request routes to it in Ring 2.
4. **When hybrid *does* become the right call.** Document this explicitly for `04-pipeline-steps.md` and future real engagements: hybrid bridging is the correct recommendation once (a) the estate has subsystems with genuinely different migration risk/value profiles, (b) a subsystem depends on infrastructure (CICS, IMS) not yet supported by this platform version, or (c) business continuity requires an incremental cutover measured in months per subsystem rather than an atomic switch. None of those conditions hold for the demo repo; they will hold for real enterprise engagements, at which point the modular-monolith boundary from §2 is precisely what makes a subsystem-by-subsystem hybrid rollout possible without a redesign — migrated and not-yet-migrated subsystems are already separate projects/modules, so an interop façade at that boundary is additive, not a retrofit.

## 7. Cross-references

- `02-harness-orchestration.md` — which agent harness runs this pipeline, session/context management, multi-agent coordination for parallel migration units.
- `03-skills.md` — concrete skills/tools each agent role invokes (COBOL parsing, C# codegen, parity harness invocation).
- `04-pipeline-steps.md` — the step-by-step pipeline (parse → IR → synthesize → build → test → parity → gate → deploy) instantiated for this demo repo.
- `05-unit-testing.md` — unit test generation strategy for the generated C#.
- `06-parity-testing.md` — the COBOL/Node/C# three-way parity harness referenced in §6.
- `07-e2e-demo.md` — the scripted end-to-end demo flow over this architecture.
- `08-bug-resolution.md` — agentic diagnosis + deterministic verification loop for parity failures, per §3.3.
- `09-observability-progress.md` — the structured state store referenced in §3.1 and its Ring-1/Ring-2 backing store.
- `10-dashboard-ui.md` — the dashboard consuming the state store from `09-observability-progress.md`.
- `11-onboarding.md` — how a new engineer or new COBOL estate onboards onto this architecture.
- `12-data-modeling.md` — the `IAccountStore`/domain-type modeling referenced in §2 and §5, generalized for copybook-derived types.
