# Wizard UI — Synthesized Design (from 3 Codex design agents)

Sources: design-a-stepper (navigation pattern), design-c2-genai (GenAI conventions),
density decisions resolved by orchestrator after design-b delivery failed twice
(grounded in ui-ux-pro-max `virtualize-lists` rule: virtualize/collapse at 50+ items).

## Navigation (from proposal A — adopted wholesale)

- **Linear-gated forward, free backward.** Forward locked until prior step's async work
  resolves (can't Explore before intake 200, can't Propose before Phase 3 OK). Backward
  always free and non-destructive.
- **SSE owned by a top-level RunContext, not the Step 5 component.** Navigating away
  stops rendering the feed, never unsubscribes. Returning replays buffered events from
  the full event log kept in context.
- **Per-step state chips independent of active step**: PENDING (grey, locked) / ACTIVE
  (spinner) / DONE (check) / DONE-WITH-WARNINGS (check + amber dot) / **LIVE (pulsing
  dot, shown on Step 5's tab even when user is on another step)** — the LIVE badge is
  the direct fix for "no veo qué está pasando" while navigating.
- **Step 4 (Corrections) always visible, disabled empty state** — never hide a
  structural pipeline step; hiding misrepresents the architecture. Empty state text
  explains Phase 7 is SKIPPED by design this round.

## Steps

1. **Onboarding** — deterministic-vs-agentic explainer + dropzone. "Start Intake"
   disabled until file selected; advance gated on intake 200.
2. **Exploration** — FileTree (left) + structural summary (right): file count, LOC,
   CALL graph. Advance gated on Phase 3 OK.
3. **Architecture Proposal** — read-only target C# shape + phase order. Sourced from
   design/01-architecture.md content, presentational this round.
4. **Corrections** — ApprovalGate; renders disabled empty state while
   `gate_status === "none"`.
5. **Migrate & Test** — ActivityFeed + PhaseTimeline + final run summary.

## GenAI visual language (from proposal C2 — adopted wholesale)

- **Deterministic rows (P0/1/3/6)**: grey/neutral gear icon, static label, instant
  snap to final state, no animation.
- **Agentic rows (P2/4/5)**: violet accent icon that pulses while RUNNING, verb-in-
  progress label ("Extracting business rules…"), subtle violet left-border — the eye
  learns "colored border = LLM did work here."
- **Agentic working state**: spinner + rotating one-line status text from real tool
  activity. Progress bar ONLY when a countable unit exists (files done/total);
  indeterminate spinner for uncountable work — never fake a percentage.
- **ApprovalGate (when it activates, future round)**: side-by-side diff (COBOL left,
  C# right), batch Accept All + per-file Accept/Reject, single batch-level comment box.
  Never auto-advance past the gate — explicit click required even with zero rejections.
- **Cost**: inline per-phase cost chip on agentic rows ("$0.42 · 12k tok") + aggregate
  corner counter. Cost is a first-class signal, not hidden in a details panel.

## Density (orchestrator decisions, 55+ file repos)

1. **ActivityFeed**: group-by-phase collapsible sections. Current phase auto-expanded
   streaming rows; completed phases auto-collapse to a one-line summary
   ("Phase 0 ✓ 55 files · 0.8s", click to expand). No virtualization library needed at
   this scale once grouped; revisit past ~500 rows.
2. **FileTree**: default collapsed to top-level dirs with per-dir file counts;
   per-file status dots synced live with feed events (tree = spatial view of the same
   stream). Expand persists per session.
3. **Glanceable** (always visible): overall progress, current file being processed,
   per-phase status (timeline). **Drill-down** (click): CALL graph detail, cost
   breakdown, per-file event history.
4. **Layout at 1280px**: 3 columns — tree 280px fixed / feed flex / timeline 320px
   fixed. Below 1024px the side panes collapse to toggleable drawers.

## Design tokens (Cobalt, resolved earlier via ui-ux-pro-max)

Background #0F172A · Card #1B2336 · Border #475569 · Foreground #F8FAFC ·
Muted-fg #94A3B8 · Accent/OK #22C55E · Agentic accent #8B5CF6 (violet) ·
Destructive #EF4444 · Warning #D29922 · Fonts: JetBrains Mono (code/feed) +
IBM Plex Sans (UI). Focus rings visible, prefers-reduced-motion respected,
no emoji icons (inline SVG, 1.5px stroke).

## Backend contract this design requires (matches approved plan §2)

- `FileEvent {type:"file", run_id, phase, file_path, status, detail}` and
  `PhaseEvent {type:"phase", ...}` multiplexed on one SSE stream.
- No artificial sleep on stub phases; pacing comes from real per-file work only.
- `gate_status: "none"|"pending"|"approved"|"rejected"` on RunStatusResponse.
