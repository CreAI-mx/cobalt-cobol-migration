---
name: migration-cost-governance
description: Cross-cutting skill — tracks token/cost spend per agent call across every phase, enforces a 4-layer budget cap (request/workflow/tenant/org). Not a pipeline phase; wraps every LLM invocation. Triggers on every headless Claude Code call in the pipeline.
---

# Migration Cost Governance

Purpose: prevent silent cost explosion — 3 agents can cost 10x, not 3x, from compounded context (documented failure mode in multi-agent pipelines).

## Instrumentation
Every headless Claude Code call (`--output-format json`) returns `total_cost_usd` and per-model token breakdown. Log one `cost_logs` row per call: `phase`, `agent_id`, `input_tokens`, `output_tokens`, `cost_usd`, `latency_ms`.

## Budget layers (check in this order, first hard-fail wins)
1. **Request** — single call exceeds expected token ceiling for its phase → hard-fail or truncate context.
2. **Workflow** — cumulative spend for this `run_id` exceeds threshold → reroute remaining files to a cheaper model tier or trim context.
3. **Tenant** — soft-warn notification, does not block.
4. **Org** — hard-fail + immediate alert.

## Rule
Never let a retry loop run unbounded. Cap turns per phase call explicitly (`--max-turns`) — suggested 5 for review-only jobs, 15 for build-and-iterate jobs. A capped-out retry is a FAILED phase status, not a silent partial success.

## Output
`cost_logs` rows, queryable via `GET /migration/{run_id}/cost` (see design/09-observability-progress.md).
