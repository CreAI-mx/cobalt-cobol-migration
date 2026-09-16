# 09 — Observability & Progress-Tracking API

Status: DRAFT design (no implementation). Scope: REST/JSON API surface for tracking an
agentic COBOL→C# migration run, per-span cost/token attribution, and a 4-layer budget cap
model. Demo target: `/home/frg/creai/cobol/cobol-accounting-system`.

## 1. Domain model

A **migration run** (`run_id`, UUIDv7 for time-sortable IDs) processes a set of COBOL
source units (programs, copybooks, JCL) through a pipeline of **agent phases**
(e.g. `parse`, `semantic-extract`, `translate`, `unit-test-gen`, `parity-test`,
`review`, `bugfix`). Each phase, for each file, executes one or more **agent spans** —
the atomic unit of LLM work an agent framework (Claude Agent SDK, Strands, MSFT Agent
Framework) emits. Spans nest: a phase span contains tool-call spans and LLM-call spans.

```
run
 └─ file_unit (per COBOL source file)
     └─ phase (parse | translate | test-gen | parity | review | bugfix)
         └─ span (agent_id, tool or llm call)
             └─ child spans (retries, sub-agent delegation)
```

Every span attributes tokens/cost/latency independently (Langfuse-style) and rolls up
to file_unit → phase → run → tenant → org. Rollups are maintained incrementally (no
full re-aggregation per request) via counters updated on span-close.

## 2. REST/JSON endpoints

Base path: `/api/v1/migration`. All responses are JSON; timestamps are RFC3339 UTC.
Auth: bearer token scoped to `org_id`/`tenant_id` (see §4). Pagination via
`?cursor=&limit=` (opaque cursor, default limit 50, max 500).

### 2.1 `GET /migration/{run_id}/status`

Top-level run status — polling target for a dashboard or CLI.

```json
{
  "run_id": "018f4d2a-...",
  "tenant_id": "creai-mx",
  "target_repo": "cobol-accounting-system",
  "state": "running",
  "phase_counts": {
    "queued": 3, "running": 2, "succeeded": 41, "failed": 1, "needs_review": 2
  },
  "started_at": "2026-09-14T12:00:00Z",
  "updated_at": "2026-09-14T12:41:10Z",
  "eta_estimate_seconds": 1380,
  "current_phase": "translate",
  "files_total": 49,
  "files_done": 41,
  "budget_state": {
    "workflow_pct_used": 62.4,
    "tenant_pct_used": 18.1,
    "org_pct_used": 4.7,
    "throttled": false
  },
  "last_error": null
}
```

`state` enum: `queued | running | paused | failed | succeeded | needs_review | cancelled`.
A run enters `paused` when a budget cap trips (see §4) and requires operator approval
via `POST /migration/{run_id}/resume`.

### 2.2 `GET /migration/{run_id}/files`

File-level progress, one row per COBOL source unit. Supports `?state=` filter and
`?phase=` filter.

```json
{
  "run_id": "018f4d2a-...",
  "items": [
    {
      "file": "src/AccountsReceivable.cbl",
      "unit_type": "program",
      "state": "translate.running",
      "phases": {
        "parse":            { "state": "succeeded", "duration_ms": 820,  "spans": 3 },
        "semantic_extract":  { "state": "succeeded", "duration_ms": 4210, "spans": 7 },
        "translate":         { "state": "running",   "duration_ms": null, "spans": 2 },
        "unit_test_gen":     { "state": "queued" },
        "parity_test":       { "state": "queued" },
        "review":            { "state": "queued" }
      },
      "output_files": [],
      "loc_source": 1180,
      "loc_generated": 0,
      "cost_usd_running": 0.41,
      "tokens_running": 38210
    }
  ],
  "next_cursor": "eyJvZmZzZXQiOjUwfQ=="
}
```

`unit_type`: `program | copybook | jcl | proc`. `state` is `{phase}.{substate}` for the
active phase, or a terminal value (`succeeded`, `failed`, `needs_review`).

### 2.3 `GET /migration/{run_id}/files/{file_id}/spans`

Drill-down: every span emitted for one file, in execution order. This is the
Langfuse-equivalent trace view for a single unit.

```json
{
  "file": "src/AccountsReceivable.cbl",
  "spans": [
    {
      "span_id": "01F2...",
      "parent_span_id": null,
      "trace_id": "018f4d2a-...:AccountsReceivable.cbl",
      "agent_id": "translator-claude-sonnet-5",
      "agent_framework": "claude-agent-sdk",
      "phase": "translate",
      "span_kind": "llm_call",
      "model": "claude-sonnet-5",
      "started_at": "2026-09-14T12:31:02.100Z",
      "ended_at": "2026-09-14T12:31:09.870Z",
      "latency_ms": 7770,
      "tokens": { "input": 12480, "output": 2140, "cache_read": 8200, "cache_write": 0 },
      "cost_usd": 0.1834,
      "status": "ok",
      "retry_count": 0,
      "tool_calls": ["read_file", "write_file"],
      "metadata": {
        "prompt_version": "translate-v3",
        "temperature": 0.0,
        "cobol_paragraph": "1000-VALIDATE-ACCOUNT"
      }
    }
  ],
  "next_cursor": null
}
```

`span_kind` enum: `llm_call | tool_call | agent_delegate | validation | retry`.
Cost is computed at span-close from `tokens` and the model's rate card (§3.2); it is
never estimated client-side, only served pre-computed.

### 2.4 `GET /migration/{run_id}/cost`

Cost/token rollup, with `?group_by=phase|agent|model|file` (default `phase`) and
`?since=`/`?until=` for windowed rollups.

```json
{
  "run_id": "018f4d2a-...",
  "group_by": "phase",
  "currency": "USD",
  "totals": { "cost_usd": 214.77, "tokens_input": 9142300, "tokens_output": 1310420 },
  "breakdown": [
    {
      "key": "parse",
      "cost_usd": 8.02,
      "tokens_input": 410200, "tokens_output": 12300,
      "span_count": 147, "avg_latency_ms": 640
    },
    {
      "key": "translate",
      "cost_usd": 152.30,
      "tokens_input": 6800000, "tokens_output": 980000,
      "span_count": 512, "avg_latency_ms": 8100
    },
    {
      "key": "parity_test",
      "cost_usd": 41.10,
      "tokens_input": 1600000, "tokens_output": 260000,
      "span_count": 203, "avg_latency_ms": 4300
    }
  ]
}
```

### 2.5 Supporting endpoints

- `POST /migration` — create a run (`target_repo`, `tenant_id`, `phase_config`, budget
  overrides). Returns `202` with `run_id` + `status` URL.
- `POST /migration/{run_id}/pause` / `POST /migration/{run_id}/resume` — operator
  control; `resume` requires a `budget_override_token` if paused by cap trip.
- `POST /migration/{run_id}/cancel` — cooperative cancel; in-flight spans finish,
  no new phases start.
- `GET /migration/{run_id}/budget` — full 4-layer budget snapshot (§4.4).
- `GET /migration` — list runs, `?tenant_id=&state=`.
- `GET /migration/{run_id}/events` — Server-Sent Events stream of state transitions
  and budget-threshold crossings, for live dashboards (`text/event-stream`); same
  payload shapes as the `status`/`cost` polling endpoints, emitted on change instead
  of polled.

## 3. Per-span cost/token attribution (Langfuse-style)

### 3.1 Span schema (canonical, stored + served)

| field | type | notes |
|---|---|---|
| `span_id` | string | ULID, globally unique |
| `trace_id` | string | `{run_id}:{file}` — groups all spans for one unit |
| `parent_span_id` | string\|null | nesting for delegate/tool sub-calls |
| `agent_id` | string | logical agent identity, e.g. `translator-claude-sonnet-5` |
| `agent_framework` | enum | `claude-agent-sdk \| strands \| msft-agent-framework \| custom` |
| `phase` | enum | pipeline phase this span belongs to |
| `span_kind` | enum | `llm_call \| tool_call \| agent_delegate \| validation \| retry` |
| `model` | string | provider model id, e.g. `claude-sonnet-5` |
| `tokens.input/output/cache_read/cache_write` | int | raw usage from provider response |
| `cost_usd` | decimal(12,6) | computed once, immutable after span close |
| `latency_ms` | int | wall clock, span open→close |
| `status` | enum | `ok \| error \| timeout \| cancelled` |
| `retry_count` | int | attempts before this span closed |
| `metadata` | object | free-form, framework-specific (prompt version, temperature, COBOL construct) |

### 3.2 Cost computation

Cost is computed server-side at span close: `cost_usd = f(model, tokens)` against a
versioned rate card (`rate_card_version` stamped on the span for auditability — rate
changes never retroactively alter historical cost). Cache-read tokens are priced at
the provider's cache-read rate, not full input rate — material for this pipeline since
COBOL copybook context is heavily cache-hit across phases.

### 3.3 Rollup strategy

Counters are maintained at 4 granularities, updated transactionally on span close:
`file_unit`, `phase` (per file_unit), `run`, and the budget-layer aggregates in §4.
`GET .../cost` reads pre-aggregated rollups, not raw spans, so it stays O(1) in span
count. Raw span drill-down (§2.3) reads the trace store directly and is paginated.

## 4. Four-layer budget cap model

Layers, outer to inner containment: **org → tenant → workflow (run) → request (span)**.
Each layer has an independent `soft_limit_usd` (warn) and `hard_limit_usd` (block new
spans, does not kill in-flight work). A cap trip at any layer pauses the run (state
`paused`) and requires `POST /migration/{run_id}/resume` with an override token scoped
to the tripped layer.

| layer | scope | typical cap | enforcement point | breach action |
|---|---|---|---|---|
| **request** | single span (one LLM call) | e.g. $2.00 / 200k tokens | pre-call estimate check in agent framework wrapper | reject the call before dispatch; span recorded as `status: rejected` |
| **workflow** | one migration run (`run_id`) | e.g. $300 / run, set at `POST /migration` | on span close, after rollup update | pause run at next phase boundary; in-flight spans complete |
| **tenant** | all runs for one tenant | e.g. $2,000 / rolling 24h | on span close, tenant rollup check | pause tenant's queued runs; running runs finish current phase, no new phase starts |
| **org** | all tenants | e.g. $10,000 / rolling 24h, or explicit monthly ceiling | on span close, org rollup check | global soft-stop: no new runs accepted (`POST /migration` returns `429 budget_exhausted`); existing runs drain |

### 4.1 Precedence

Checks run innermost-first (request → workflow → tenant → org) so a request-level
reject never needs to consult outer layers, but any outer-layer hard breach overrides
an inner layer's "ok" — a tenant-level trip pauses a run even if that run's own budget
has headroom.

### 4.2 Soft vs hard limits

- **Soft limit** (default 80% of hard): emits a budget-threshold event on the SSE
  stream and sets `budget_state.*_pct_used` in `GET .../status`; no blocking.
- **Hard limit**: blocks new span dispatch at that layer; existing in-flight spans are
  allowed to finish (never killed mid-call — avoids partial/corrupt LLM output states).

### 4.3 Estimation vs actual

Request-layer enforcement necessarily uses a **pre-call estimate** (prompt token count
+ configured max-output tokens × rate card) since actual cost isn't known until the
call returns. Workflow/tenant/org layers enforce on **actual** cost from closed spans,
so estimate error at the request layer is bounded by that single call and never
compounds upward.

### 4.4 `GET /migration/{run_id}/budget` response

```json
{
  "run_id": "018f4d2a-...",
  "layers": {
    "request":  { "hard_limit_usd": 2.00,   "soft_limit_usd": 1.60,  "scope": "per_span" },
    "workflow": { "hard_limit_usd": 300.00, "soft_limit_usd": 240.00, "spent_usd": 214.77, "pct_used": 71.6 },
    "tenant":   { "hard_limit_usd": 2000.00, "soft_limit_usd": 1600.00, "spent_usd": 361.20, "pct_used": 18.1, "window": "rolling_24h" },
    "org":      { "hard_limit_usd": 10000.00, "soft_limit_usd": 8000.00, "spent_usd": 470.90, "pct_used": 4.7, "window": "rolling_24h" }
  },
  "trips": [],
  "as_of": "2026-09-14T12:41:10Z"
}
```

`trips` lists any layer currently in breach:
`{"layer": "workflow", "kind": "hard", "tripped_at": "...", "requires_override": true}`.

## 5. Error model

All non-2xx responses:
```json
{ "error": { "code": "budget_exhausted", "message": "...", "layer": "tenant" } }
```
Standard codes: `run_not_found`, `file_not_found`, `invalid_state_transition`,
`budget_exhausted`, `override_token_invalid`, `validation_error` (400).

## 6. Open questions (for implementation phase, not resolved here)

- Trace/span storage backend (OpenTelemetry-compatible store vs. bespoke Postgres
  rollup tables vs. direct Langfuse self-host) — affects §2.3 pagination cost model.
- Whether `agent_delegate` spans (sub-agent calls, e.g. Claude Agent SDK subagents)
  attribute cost to the parent phase or split proportionally — recommend: cost stays
  on the span that incurred it, phase rollup sums the whole subtree.
- Rate-card update process and versioning store (§3.2) — needs an admin endpoint,
  out of scope here.
