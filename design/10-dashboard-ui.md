# 10 — Dashboard UI for Agentic COBOL→C# Migration Pipeline

Status: design only, no implementation.
Target repo under migration: `/home/frg/creai/cobol/cobol-accounting-system` (COBOL sources `main.cob`, `data.cob`, `operations.cob`, plus `node-accounting-app/` as an existing reference port).
Consumes: `09-observability-progress.md` endpoints (status/files/cost), assumed conceptually as described below since that doc is not present in this repo checkout — endpoint shapes are inferred from pipeline stage needs and should be reconciled against the actual doc when it lands.

## 1. Purpose and audience

Two operating modes, one UI, mode-switched by a top-bar toggle:

- **Demo mode**: stakeholder-facing, replay or live run against the sample COBOL repo, emphasis on narrative clarity (what is happening, why, what changed) over density.
- **Production mode**: engineer-facing, emphasis on density, drill-down, and gating actions (approve/reject/rerun) across a real migration batch spanning many COBOL programs.

Primary user goal in both modes: answer "where is the pipeline right now, what did it produce, can I trust it, and does a human need to act."

## 2. Information architecture

Five top-level views, reachable from a persistent left nav. A global run selector (dropdown, top bar) scopes every view to one pipeline run (`run_id`); production mode additionally allows a multi-run comparison view (§2.6).

1. Pipeline Overview (live progress) — default landing view
2. Dependency Graph
3. Code Diff Viewer (COBOL vs C#)
4. Parity Test Results
5. Cost & Token Governance

Plus a persistent, non-navigational **Approval Gate tray** (§7) that surfaces across all views whenever a gate is pending.

### 2.1 Navigation shell

```
┌─────────────────────────────────────────────────────────────────┐
│ [logo] Migration Console      Run: [cobol-accounting-system ▾]  │
│                                  Mode: (Demo) (Production)        │
│                                  ● 3 files awaiting approval  [▾] │
├───────────┬───────────────────────────────────────────────────────┤
│ Overview  │                                                       │
│ Graph     │                    <view content>                    │
│ Diffs     │                                                       │
│ Parity    │                                                       │
│ Cost      │                                                       │
├───────────┴───────────────────────────────────────────────────────┤
│ status bar: WS connected · last event 2s ago · agent: r3-cobol… │
└─────────────────────────────────────────────────────────────────┘
```

Left nav item badges show live counts (e.g. Parity: "2 failing"). Status bar bottom-left shows the observability WebSocket/SSE connection state — this is the single most important trust signal in a live demo, so it must never be silently stale.

### 2.2 Run selector

Backed by `GET /api/runs` (list) and `GET /api/runs/{run_id}/status` (detail, polled or streamed). Each run entry: `run_id`, `repo_path`, `started_at`, `phase` (queued/running/paused/completed/failed), `overall_progress_pct`.

### 2.3 Demo vs production mode deltas

| Aspect | Demo | Production |
|---|---|---|
| Data source | replay buffer (recorded run) or live sandbox run | live orchestrator only |
| Density | one file in focus, big type, animated transitions | dense table, sortable, no animation beyond state icons |
| Approval gate | auto-advance after N seconds unless presenter clicks pause | strictly blocking, requires explicit human action |
| Cost panel | rounded, illustrative ("~$0.42 so far") | exact, per-call breakdown, budget alerts |
| Multi-run compare | hidden | available (§2.6) |

A single React app; mode is a context value, not a separate build.

### 2.4 File/phase unit model

The atomic unit of progress is `(file, phase)`. Phases, fixed pipeline order (matches the multi-agent roles already active in this session: d03/d04/r3/r8 parse+transform, d05/r10 test-gen, d06/r4 parity, d09 observability):

`DISCOVERED → PARSED → SEMANTIC_MODEL → TRANSFORMED (C# draft) → UNIT_TESTED → PARITY_TESTED → HUMAN_REVIEW → APPROVED/REJECTED → MERGED`

Each file tracks current phase, phase history with timestamps and durations, current agent/worker id, and status (`ok`, `warn`, `error`, `blocked_on_human`).

### 2.5 Pipeline Overview screen

Two panes:

- **Left (60%)**: file table, one row per COBOL source file being migrated (`main.cob`, `data.cob`, `operations.cob`, …). Columns: file, current phase (pill), progress within phase, elapsed time, agent, status icon. Row click opens a right-side detail drawer with full phase timeline (horizontal Gantt-like strip, one segment per phase, colored by outcome) and a "Jump to Diff" / "Jump to Parity" shortcut.
- **Right (40%, in Overview only)**: aggregate cards — overall % complete, files in each phase (stacked bar), active agents, ETA (linear extrapolation from phase-duration history, labeled "estimate" not a guarantee).

Data: `GET /api/runs/{run_id}/files` for the table snapshot, then `WS /api/runs/{run_id}/events` (or SSE `GET /api/runs/{run_id}/events/stream`) for incremental phase-transition events: `{file, from_phase, to_phase, timestamp, agent_id, status}`. Table updates by patching rows, never full re-fetch, to keep the transition animation legible in demo mode.

### 2.6 Multi-run comparison (production only)

A compact table view: rows = runs, columns = overall progress, parity pass rate, total cost, duration, gate-pending count. Used to compare e.g. a rerun after a bugfix against the prior attempt. Backed by `GET /api/runs?repo_path=...&limit=...`.

## 3. Dependency Graph view

Purpose: show call/copy/include dependencies between COBOL programs (and, once transformed, the resulting C# project/namespace structure), so a reviewer understands blast radius before approving a file.

- Node = COBOL program or copybook (for this repo: `main.cob`, `data.cob`, `operations.cob`, plus any `COPY` targets); node color = current phase (same palette as Overview); node border = status (error/warn ring).
- Edge = static dependency (CALL, COPY, PERFORM of external paragraph) extracted during PARSED/SEMANTIC_MODEL phase.
- Toggle: "COBOL view" / "C# view" / "overlay" — overlay draws a dashed line from each COBOL node to its generated C# counterpart(s), useful when one COBOL program is split into multiple C# classes (common when PERFORM sections become separate services).
- Layout: force-directed for exploration, with a "freeze layout" toggle so positions don't jitter during a live demo; fallback to a fixed DAG (dagre-style layered) layout for production screenshots/reports since it's more legible for audits.
- Click node → opens the same file detail drawer as Overview; click edge → shows the specific COBOL statement(s) establishing the dependency (line-numbered).
- Filter bar: by phase, by status, by "has pending approval," text search by program name.

Data: `GET /api/runs/{run_id}/graph` returning `{nodes: [{id, kind: cobol|csharp, phase, status}], edges: [{from, to, kind: call|copy|generated_from}]}`. Recomputed once per SEMANTIC_MODEL completion; graph is not expected to stream at high frequency, so poll every 5–10s or refresh on a `graph_updated` WS event rather than diffing every node.

Library: React + `reagraph` or `@xyflow/react` (React Flow) for interactive graphs with custom node renderers; avoid raw D3 for graph layout — use D3 only for the smaller charts in Cost/Overview (see `dataviz` skill guidance — one system, consistent palette across all charts and graph node-status colors).

## 4. Code Diff Viewer (COBOL vs C#)

Side-by-side, COBOL left / generated C# right, synchronized scroll, powered by Monaco's diff editor in "inline-mapped" mode rather than literal line diff (COBOL and C# are not line-isomorphic, so a naive text diff is close to useless here).

Two sub-modes, switchable per file:

- **Semantic mapping mode** (default): COBOL source annotated with colored region markers; each region links to the C# region it produced. Selecting a COBOL paragraph (e.g. a `PERFORM` block in `operations.cob`) highlights the corresponding C# method. Requires the transform agent to emit a mapping artifact (`{cobol_range, csharp_range, construct_kind}` list) alongside the generated code — this is a **new artifact requirement** on the transform phase, called out explicitly since it doesn't exist by default in a naive transpile step.
- **Raw diff mode**: fallback when no mapping artifact exists yet (e.g. file mid-TRANSFORMED, mapping not finalized) — shows COBOL and C# as two independent read-only panes without a diff algorithm across languages (a cross-language line diff is misleading; don't ship one).

Header bar per file: phase pill, "regenerate" action (production only, requires confirmation — regenerating discards the current C# draft), "view mapping artifact JSON" (debug affordance), approve/reject buttons wired to the Approval Gate (§7).

Data: `GET /api/runs/{run_id}/files/{file_id}/cobol` (source + line metadata), `GET /api/runs/{run_id}/files/{file_id}/csharp` (generated source + mapping artifact). Both are point-in-time reads (no streaming needed); re-fetch on phase-transition event for that file.

## 5. Parity Test Results

Parity here means: run the same input through the original COBOL (or its behavior spec) and the generated C#, compare outputs. Given `TESTPLAN.md` and `r4-parity-testing` as an active role, the UI should assume parity tests are enumerated up front, not discovered ad hoc.

Layout: table, one row per parity test case. Columns: test id/name, target file(s), input summary, COBOL output, C# output, verdict (pass/fail/error), diff size (for numeric/financial fields — accounting domain — show delta with currency formatting, not raw floats).

- Row expand → structured field-by-field comparison (important for an accounting system: rounding/truncation mismatches on decimal fields are the highest-value bug class to surface clearly — highlight any field where COBOL `COMP-3`/`PIC` decimal semantics diverge from C# `decimal` output).
- Top summary bar: pass rate %, count by verdict, "flaky" count (tests whose verdict changed across reruns without a code change — track via `{test_id, run_attempt}` history).
- Filter/sort by file, verdict, delta magnitude.
- Action: "rerun failing" (production only) — triggers a scoped re-execution request, does not silently retry.

Data: `GET /api/runs/{run_id}/parity` returning per-test results; `WS` event `parity_result` for live updates as PARITY_TESTED completes per file, so the table populates incrementally rather than blocking on the whole suite.

## 6. Cost & Token Governance

Given `r5-cost-governance` as an active role, this view is a first-class screen, not a footer widget.

- Top cards: total tokens (in/out), total cost (USD), cost per file (avg), projected total cost at current burn rate (extrapolated from files remaining × avg cost/file — label as estimate).
- Time-series chart: cost accumulation over run duration, stacked by phase (transform is typically the dominant cost center; unit-test generation second) — stacked area, using the dataviz skill's sequential palette per phase to stay consistent with the phase-color legend used in Overview/Graph.
- Table: per-agent-call breakdown (model, tokens in/out, cost, file, phase, timestamp) — sortable, exportable to CSV for finance/reporting.
- Budget bar: configured budget ceiling vs current spend, with a warning threshold (e.g. 80%) that raises a banner — in production mode this banner should also be able to *pause* the pipeline (a control the observability doc's cost endpoint presumably exposes as a threshold-breach event); demo mode shows the same banner without the pause capability so a live demo doesn't halt mid-presentation on a synthetic budget.

Data: `GET /api/runs/{run_id}/cost` (aggregate + time series), `GET /api/runs/{run_id}/cost/calls` (paginated per-call ledger), `WS` event `cost_update` for live ticking of the top cards during a run.

## 7. Human Approval Gate UI

Cross-cutting, not a standalone screen. Two surfaces:

1. **Approval tray** (top bar, all views): badge with pending count, click opens a slide-over panel listing every file currently at `HUMAN_REVIEW`, each with a one-line summary (parity verdict, diff size, cost so far) and inline Approve/Reject/Request-changes buttons — lets a reviewer clear the queue without leaving the current view.
2. **In-context gate** (Diff Viewer, Parity view): the same three actions appear docked at the bottom of the file detail whenever that file is at `HUMAN_REVIEW`, so approval happens where the evidence is being read, not just from the tray.

Gate actions:
- **Approve** → `POST /api/runs/{run_id}/files/{file_id}/approve` `{reviewer, note?}` → phase advances to `APPROVED`/`MERGED`.
- **Reject** → `POST .../reject` `{reviewer, reason}` → phase reverts to `TRANSFORMED` (or earlier), triggers a re-transform request; reason is mandatory and surfaces to the transform agent as feedback context.
- **Request changes** → same endpoint family with a structured note, non-blocking (pipeline can continue other files) — distinguishes "this is wrong, redo it" from "this is fine but note X for later."

Design constraint: approval is the one action in this UI with real, hard-to-reverse consequences (merging generated C# into the target system). Require an explicit confirm step (not a single click) for Approve on any file whose parity verdict is not 100% pass, and always show the parity + diff snapshot inline in the confirm dialog so approval can't happen blind.

WS event `gate_opened`/`gate_closed` keeps the tray badge and in-context docks in sync across multiple reviewers/tabs without polling.

## 8. Tech stack recommendation

- **Framework**: React + TypeScript, Vite build. Rationale: team is already producing React output for the migration target's companion `node-accounting-app`; reusing the same language/tooling for the dashboard avoids a second stack to maintain, and React Flow/Monaco both have first-class React bindings.
- **State/data**: TanStack Query for all REST reads (caching, polling fallback, retry/backoff when WS drops), a thin Zustand store for cross-view UI state (selected run, mode toggle, gate tray open state) — avoid Redux, this app's client state is small.
- **Realtime**: native WebSocket client wrapped in a small reconnect-with-backoff hook; fall back to SSE if the observability backend only exposes `/events/stream`; fall back further to polling (`GET /status` every 3–5s) if neither is available — the UI must degrade gracefully rather than blank out, since a stalled connection during a live demo is the worst failure mode.
- **Graph**: `@xyflow/react` (React Flow) for the dependency graph — good custom-node support, decent default performance up to a few hundred nodes (sufficient for this repo's 3 files and any realistic production batch in the tens-to-low-hundreds range; if a production migration exceeds ~500 nodes, plan a follow-up to swap in `reagraph`/WebGL rendering rather than over-engineering this up front, per YAGNI).
- **Diff editor**: `@monaco-editor/react` with the diff-editor API, custom decorations for semantic-mapping mode (Monaco's default diff algorithm is disabled in that mode; decorations + a custom minimap are hand-driven from the mapping artifact).
- **Charts**: lightweight (Recharts or a thin D3 wrapper) for the cost time-series and progress bars, following the `dataviz` skill's palette/formula so chart colors, phase-pill colors, and graph node-status colors are one consistent system rather than three independently invented ones.
- **Styling**: Tailwind CSS + a small design-token layer (phase colors, status colors as named tokens, not ad hoc hex) so demo/production mode density differences are theme variants, not forked components.
- **Testing**: Vitest + React Testing Library for components; Playwright for the two critical E2E flows — "watch a run complete end-to-end" and "approve/reject a gated file" — per this org's e2e-testing standard.

## 9. Endpoint consumption summary

| View | Reads | Streams | Writes |
|---|---|---|---|
| Overview | `GET /runs`, `GET /runs/{id}/status`, `GET /runs/{id}/files` | `events` (phase transitions) | — |
| Graph | `GET /runs/{id}/graph` | `graph_updated` | — |
| Diff Viewer | `GET /runs/{id}/files/{fid}/cobol`, `.../csharp` | `events` (per-file) | approve/reject (via gate) |
| Parity | `GET /runs/{id}/parity` | `parity_result` | rerun-failing (prod only) |
| Cost | `GET /runs/{id}/cost`, `.../cost/calls` | `cost_update`, `budget_threshold` | pause-on-budget (prod only) |
| Approval gate | `GET /runs/{id}/files?phase=HUMAN_REVIEW` | `gate_opened`/`gate_closed` | `POST .../approve`, `.../reject` |

All endpoint paths above are inferred from pipeline needs against the *assumed* `09-observability-progress.md` contract; before implementation, reconcile field names and event schema against that doc directly rather than this inference.

## 10. Open questions for implementation phase

1. Does the observability backend expose a mapping artifact for semantic diff mode, or does the transform agent need a new output contract added?
2. Is there an existing auth/reviewer-identity model to attach to `approve`/`reject` calls, or does this need a lightweight login for the demo?
3. Expected max concurrent files/run in production — sizes the graph-rendering fallback decision in §8.
4. Replay data source for demo mode (recorded event log vs live sandbox run against `cobol-accounting-system`) — affects whether the WS layer needs a "replay" transport mode.
