# Harness & Orchestration Design — Agentic COBOL→C# Migration Pipeline

Status: design only, no implementation. Target demo repo: `/home/frg/creai/cobol/cobol-accounting-system`
(3 programs: `main.cob`, `operations.cob`, `data.cob`; CALL-linked, no COPYBOOKs, no file I/O, no SQL —
chosen as the minimal harness-validation case, not representative of enterprise COBOL scale).

## 0. Governing principle

Determinism where determinism is possible; LLM only where semantic judgment is required. Concretely:

1. **Parse, don't prompt, for structure.** AST extraction, call graph, data division layout, PERFORM/PARAGRAPH
   control flow — all derived by a deterministic parser (ProLeap COBOL Parser, ANTLR-based, Java) before any
   model call. The LLM never sees raw COBOL text as its first exposure to structure; it sees a structured
   `CobolAnalysis` JSON artifact.
2. **LLM only for the scalpel step.** Business-logic explanation, target-language code synthesis, edge-case
   narrative, and review commentary go through Claude Code invoked headlessly. This mirrors why Claude Code is
   used at all here: fidelity of semantic translation (idiom, naming, structuring EVALUATE/PERFORM into C#
   control flow) is a judgment task, not a parse task.
3. **Orchestration is a typed, resumable DAG**, not a chat loop. Strands Agents SDK's `Graph` multi-agent
   pattern is the orchestrator: nodes are phases with declared input/output Pydantic models, edges are
   phase dependencies, and the Graph gives deterministic execution order, partial-failure isolation, and
   resumability — properties a single long conversational agent does not give for free.
4. **State is files on disk, not conversation history.** Every phase reads/writes a versioned artifact under
   `migration-state/<phase>/<unit>.json`. This is what makes the pipeline resumable, auditable, diffable, and
   reviewable without replaying model calls.

This directly mirrors the Azure-Samples/Legacy-Modernization-Agents artifact taxonomy
(`CobolAnalysis` → `BusinessLogic` → `DependencyMap` → generated `CodeFile`), adapted to a Strands `Graph`
orchestrator driving Claude Code as the code-generation/review tool instead of Semantic Kernel agents.

## 1. Pipeline phases (Graph nodes)

```
                    ┌─────────────────┐
                    │ 0. Ingest        │  deterministic
                    └────────┬─────────┘
                             │
                    ┌────────▼─────────┐
                    │ 1. Parse (ProLeap)│  deterministic
                    └────────┬─────────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
      ┌───────────────┐ ┌──────────┐ ┌──────────────┐
      │ 2a. DependencyMap│ │2b. DataModel│ │2c. ControlFlow│   deterministic, parallel
      └───────┬───────┘ └────┬─────┘ └──────┬───────┘
              └──────────────┼──────────────┘
                             ▼
                    ┌──────────────────┐
                    │ 3. BusinessLogic  │  LLM (Claude Code, read-only tools)
                    │    extraction     │
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │ 4. Code Synthesis │  LLM (Claude Code, write tools, scoped)
                    │    (per unit)     │
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │ 5. Build & Test   │  deterministic (dotnet build/test)
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │ 6. Semantic Review│  LLM (Claude Code, read-only, adversarial)
                    └────────┬─────────┘
                             ▼
                    ┌──────────────────┐
                    │ 7. Parity Gate    │  deterministic (golden I/O diff, see r4)
                    └──────────────────┘
```

Node granularity for the demo repo: one `CobolAnalysis` unit per COBOL program (3 units: MainProgram,
OperationsProgram, DataProgram), one `DependencyMap` for the whole graph (CALL edges: Main→Operations,
Operations→Data), phases 3–6 run per-unit but phase 4 must respect DependencyMap topological order (Data
before Operations before Main) since generated C# signatures propagate upward.

## 2. Agent roles and typed contracts

All contracts are Pydantic models, serialized to JSON on disk at `migration-state/<phase>/<unit-id>.json`.
Schema versioned (`schema_version` field) from day one — this is a 3-program demo today, will not stay one.

### 2.0 `CobolAnalysis` (output of Phase 1, deterministic — no LLM)

```python
class DataItem(BaseModel):
    level: int
    name: str
    picture: str | None
    usage: str | None            # COMP, COMP-3, DISPLAY, ...
    value: str | None
    occurs: int | None
    redefines: str | None
    parent: str | None           # name of enclosing group item

class Paragraph(BaseModel):
    name: str
    section: str | None
    statements: list[str]        # verbatim COBOL statement text, ordered
    performs_out: list[str]      # paragraphs this one PERFORMs
    calls_out: list[str]         # program-ids this one CALLs

class CobolAnalysis(BaseModel):
    schema_version: str = "1.0"
    program_id: str
    source_path: str
    source_sha256: str            # pins analysis to exact source bytes
    divisions: dict[str, bool]    # which of ID/ENV/DATA/PROCEDURE present
    working_storage: list[DataItem]
    linkage_section: list[DataItem]
    paragraphs: list[Paragraph]
    entry_points: list[str]       # USING params if any (CALL 'X' USING ...)
    calls: list[str]              # program-ids called, deduplicated
    parse_warnings: list[str]     # ProLeap diagnostics, non-fatal
```

Produced entirely by walking the ProLeap AST. No LLM in this phase — this is the ground truth every
downstream phase is graded against. `source_sha256` is the cache/invalidation key: if source hasn't changed,
skip re-parsing and every downstream phase keyed off it.

### 2.1 `DependencyMap` (Phase 2a, deterministic)

```python
class CallEdge(BaseModel):
    caller: str
    callee: str
    call_sites: list[str]         # paragraph names where the CALL occurs
    using_params: list[str]       # literal USING args at each site, e.g. "'CREDIT'"

class DependencyMap(BaseModel):
    schema_version: str = "1.0"
    programs: list[str]
    edges: list[CallEdge]
    topological_order: list[str]  # Kahn's algorithm over edges; cycle → hard fail, no LLM fallback
```

Built by graph traversal over all `CobolAnalysis.calls`. A cycle here is a correctness-blocking condition,
not a modeling question — the Graph node fails closed and the pipeline halts (no LLM is asked to "resolve" a
call cycle; that is a human decision).

### 2.2 `BusinessLogic` (Phase 3, LLM — Claude Code headless, read-only)

```python
class Rule(BaseModel):
    id: str                       # e.g. "OP-001"
    paragraph: str
    natural_language: str
    preconditions: list[str]
    postconditions: list[str]
    edge_cases: list[str]         # e.g. "debit exceeding balance: COBOL currently allows negative balance, no check"
    confidence: Literal["high", "medium", "low"]

class BusinessLogic(BaseModel):
    schema_version: str = "1.0"
    program_id: str
    source_analysis_sha256: str   # must match CobolAnalysis.source_sha256 — staleness guard
    rules: list[Rule]
    open_questions: list[str]     # ambiguities the model flags rather than silently resolving
```

This is the first LLM-touched artifact. Input to the Claude Code invocation is the `CobolAnalysis` JSON
(not raw COBOL — the model reasons over structured facts already extracted deterministically) plus the raw
source for line-level grounding. Prompted to explain what the code does and flag ambiguity, explicitly
forbidden from inventing behavior not present in the paragraphs (e.g. it must not assume overdraft
protection exists in `operations.cob` if the COBOL has no such check — call this out as `edge_cases`,
not silently "fix" it in translation). `confidence: low` rules are routed to human review before Phase 4
consumes them (gate, not advisory).

### 2.3 `CodeFile` (Phase 4, LLM — Claude Code headless, scoped write)

```python
class CodeFile(BaseModel):
    schema_version: str = "1.0"
    program_id: str
    source_business_logic_sha256: str
    target_path: str              # e.g. "csharp-accounting-system/Operations.cs"
    language: Literal["csharp"] = "csharp"
    content: str
    rules_covered: list[str]      # Rule.id list — traceability from C# back to extracted rule
    translation_notes: list[str]  # e.g. "COBOL PIC 9(7)V99 COMP-3 -> decimal, 7,2"
    generated_at: str             # ISO8601
```

`rules_covered` is the traceability spine: every `Rule.id` from Phase 3 must appear in some `CodeFile`, and
Phase 6 review checks that intersection. A rule with zero coverage is a hard gate failure, not a warning —
this is a translation completeness gate, not a comment.

### 2.4 Phase 6 review artifact — `SemanticReview`

```python
class Finding(BaseModel):
    severity: Literal["blocker", "major", "minor", "note"]
    rule_id: str | None
    description: str
    cobol_reference: str          # paragraph/line
    csharp_reference: str         # file/line

class SemanticReview(BaseModel):
    schema_version: str = "1.0"
    program_id: str
    findings: list[Finding]
    verdict: Literal["pass", "pass_with_notes", "block"]
```

Produced by a *separate* Claude Code invocation from Phase 4's — different prompt, adversarial framing
("find where this C# diverges from the COBOL semantics"), and crucially different tool scope (read-only,
see §3). Never let the generation call grade its own homework in the same context window.

## 3. Permission / determinism boundaries per phase

| Phase | Executor | Claude Code flags | Filesystem scope | Network |
|---|---|---|---|---|
| 0 Ingest | shell/Python | n/a | read source repo only | none |
| 1 Parse | ProLeap (JVM subprocess) | n/a | read source, write `migration-state/analysis/` | none |
| 2a/b/c Derive | Python (pure functions over Phase-1 JSON) | n/a | write `migration-state/derived/` | none |
| 3 BusinessLogic | Claude Code headless | `--output-format json`, `--allowedTools "Read,Grep,Glob"` (no Bash, no Write) | read source + `migration-state/analysis/`; write only its own output file via harness, not via model's own tool calls | none — `--allowedTools` excludes WebSearch/WebFetch |
| 4 CodeSynthesis | Claude Code headless | `--output-format json`, `--allowedTools "Read,Grep,Glob,Write,Edit"`, `--add-dir` restricted to target C# project subtree only | write scoped to `csharp-accounting-system/**` — never the COBOL source tree | none |
| 5 Build&Test | shell (`dotnet build`, `dotnet test`) | n/a | write build artifacts, test results | none (or restricted to package restore cache) |
| 6 SemanticReview | Claude Code headless | `--output-format json`, `--allowedTools "Read,Grep,Glob"` | read COBOL source + generated C#; write only review artifact via harness | none |
| 7 ParityGate | Python/deterministic golden-run diff (see r4 workstream) | n/a | read test outputs | none |

Rules that hold across all LLM phases:

- **Never `--dangerously-skip-permissions`.** Every headless invocation passes an explicit `--allowedTools`
  allowlist; the harness treats an unlisted tool call as the model asking for something out of scope, not
  as something to silently grant.
- **Read/write separation between generation and review is structural, not a prompt instruction.** Phase 3
  and Phase 6 literally cannot invoke `Write`/`Edit` at the CLI-flag level — this can't be talked around by
  either an adversarial input or a model refusing an instruction, because there is no instruction; the tool
  isn't offered.
  system-level.
- **Phase 4 is the only phase with `Write`/`Edit`, and only inside the target C# subtree**, enforced by
  `--add-dir` scoping the working directory Claude Code is invoked from plus the allowedTools list. The
  COBOL source tree is mounted read-only from the orchestrator's perspective — Strands never gives Phase 4's
  subprocess a cwd or `--add-dir` entry that includes `cobol-accounting-system/*.cob`.
- **No phase has blanket Bash.** If a future phase genuinely needs shell access (e.g. running a formatter),
  the allowlist enumerates the exact command prefix via `Bash(dotnet format:*)`-style scoped grants, not bare
  `Bash`.
- **Cost/token boundary per phase** (ties to r5 workstream): each Claude Code invocation gets a
  `--max-turns` cap and the orchestrator enforces a wall-clock timeout on the subprocess; a phase that blows
  its budget fails the Graph node rather than running unbounded.

## 4. Invoking Claude Code headlessly from within the Strands Graph node

Each LLM-phase Graph node is a thin Python wrapper (a Strands `@tool`-decorated function or a plain node
callable) that shells out to the Claude Code CLI as a subprocess and parses its structured output. Sketch of
the invocation contract (not full implementation):

```python
def invoke_claude_code_headless(
    prompt_file: Path,
    allowed_tools: list[str],
    cwd: Path,
    add_dirs: list[Path] | None = None,
    max_turns: int = 8,
    timeout_s: int = 300,
) -> dict:
    cmd = [
        "claude", "-p", "@" + str(prompt_file),
        "--output-format", "json",
        "--allowedTools", ",".join(allowed_tools),
        "--max-turns", str(max_turns),
    ]
    for d in (add_dirs or []):
        cmd += ["--add-dir", str(d)]
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, timeout=timeout_s, text=True)
    if result.returncode != 0:
        raise PhaseExecutionError(stderr=result.stderr, phase=prompt_file.stem)
    payload = json.loads(result.stdout)   # top-level Claude Code JSON envelope: result, usage, cost, session_id
    return payload
```

Key points:

- **`--output-format json`** gives a machine-parseable envelope (`result`, `usage.input_tokens` /
  `output_tokens`, `total_cost_usd`, `session_id`, `is_error`) — this is what feeds r5 cost governance and
  what the Graph node uses to decide pass/fail before even looking at semantic content.
- **The `result` field is expected to itself be JSON** matching the phase's Pydantic contract (`BusinessLogic`,
  `CodeFile`, etc.). The prompt for each phase explicitly instructs "respond with a single JSON object
  matching schema `<X>`, no prose outside the JSON" — the orchestrator then does
  `PhaseModel.model_validate_json(payload["result"])`. A validation failure is a Graph node failure with the
  raw payload preserved for debugging, not a silent pass-through.
- **`session_id` is captured but not reused across phases.** Each phase gets a fresh Claude Code session —
  conversation continuity is not how phase-to-phase state flows (that's the artifact files); reusing a
  session across phases would reintroduce the untyped-chat-history coupling this design is explicitly
  avoiding. `session_id` is kept only for audit/replay of a single phase's own subprocess if it needs
  re-invocation (e.g. `--resume` for a Phase-4 retry after a Phase-5 build failure, scoped to that one
  phase's own history, not the whole pipeline's).
- **Strands Graph node wraps this call as a normal Python function returning a typed result**; Strands
  itself doesn't need to know Claude Code is behind it — from the Graph's perspective this is any other node
  with declared input/output types. Strands' own model layer (`BedrockModel`, etc.) is not used to drive the
  synthesis/review steps — Claude Code is invoked as an external tool, not as a Strands `Agent` provider.
  This is a deliberate separation: Strands owns orchestration/state machine, Claude Code owns semantic edit
  fidelity. Don't let the two abstractions blur (e.g. don't attempt to have a Strands `Agent` "call" the
  Claude Code CLI as if it were a Strands tool available to sub-turns — treat each headless invocation as
  atomic, one prompt in, one JSON envelope out, no follow-up turns from the orchestrator side).

## 5. State persistence between phases

```
migration-state/
  manifest.json                      # pipeline-level: units, phase status, sha256 pins
  analysis/<program_id>.json         # CobolAnalysis
  derived/dependency-map.json        # DependencyMap  (single, whole-graph)
  derived/<program_id>.datamodel.json
  derived/<program_id>.controlflow.json
  business-logic/<program_id>.json   # BusinessLogic
  codegen/<program_id>.codefile.json # CodeFile (metadata; .content also materialized to real path)
  build/<program_id>.build.json      # dotnet build/test output, structured
  review/<program_id>.review.json    # SemanticReview
  parity/<program_id>.parity.json    # golden I/O diff result (r4)
```

`manifest.json` is the single source of truth for Graph resumability:

```python
class PhaseStatus(BaseModel):
    phase: str
    unit_id: str
    status: Literal["pending", "running", "passed", "failed", "blocked"]
    input_sha256: str            # hash of the upstream artifact(s) consumed
    output_path: str | None
    cost_usd: float | None
    updated_at: str

class Manifest(BaseModel):
    schema_version: str = "1.0"
    units: list[str]
    phases: list[PhaseStatus]
```

- Every artifact carries the sha256 of the artifact(s) it was derived from (`source_analysis_sha256`,
  `source_business_logic_sha256`, etc.). Before running a phase, the orchestrator recomputes the upstream
  hash and compares to what's recorded — if it matches and status is `passed`, the phase is skipped
  (idempotent re-run / resumability after a crash). If it doesn't match, the artifact is stale and the phase
  reruns even if a `passed` file exists.
- This is what makes "resume the pipeline after a Phase-4 crash on unit 2 of 3" a manifest read, not a
  replay of Phases 0–3.
- Strands `Graph` state (its own internal execution DAG state) tracks node completion for *this run*;
  `manifest.json` is the durable cross-run ledger the Graph consults on startup to decide which nodes to
  actually execute vs. short-circuit to their last-known artifact. Treat Strands Graph state as ephemeral
  orchestration bookkeeping and `manifest.json` as the persisted contract — don't conflate the two or the
  pipeline stops being resumable across process restarts.
- All artifacts are plain JSON (or `.cs`/`.cob` for content), checked into the same working tree as the
  source — this gives free diffability and git history over migration decisions, and lets a human `git diff`
  a `BusinessLogic` artifact the same way they'd diff code.

## 6. Failure semantics

- Deterministic phases (0,1,2,5,7) fail closed with structured errors; no LLM is asked to interpret a parser
  or build failure — that's routed to a human or to a narrowly-scoped `build-error-resolver`-style fix loop
  bounded by `--max-turns` and re-running Phase 5, capped at N retries (config, not unbounded loop).
- LLM phases (3,4,6) fail closed on: JSON schema validation failure, `is_error: true` in the Claude Code
  envelope, `confidence: low` rules unresolved, `rules_covered` incomplete, or `verdict: block` from Phase 6.
- A `block` verdict from Phase 6 routes back to Phase 4 for regeneration with the `SemanticReview.findings`
  appended to the next prompt as corrective context — bounded retry count, not an unbounded generate/review
  loop.

## 7. Open items deferred to sibling workstreams (not designed here)

- Exact ProLeap AST→`CobolAnalysis` mapping code — r8 (cobol-parsers).
- Golden-run parity harness (`Phase 7`) mechanics — r4 (parity-testing).
- Per-phase token/cost budgets and model routing — r5 (cost-governance).
- CI gating on `verdict`/`parity` before merge — r9 (cicd-gating).
- COBOL-semantics edge cases (COMP-3 rounding, PERFORM VARYING, 88-level condition names) that
  `BusinessLogic` must surface accurately — r3 (cobol-semantics).
