"""One-shot Claude Code planner. Reads a compact inventory (not the whole
estate) and returns a MigrationPlan. Falls back to work_items.fallback_plan.

Importers: orchestrator.py. API: POST /migration/{run_id}/plan.
User: un Claude Code analiza el repo una sola vez y devuelve un manifiesto.
"""
from __future__ import annotations

from pathlib import Path

from ulid import ULID

import llm
from work_items import (
    MigrationPlan,
    fallback_plan,
    inventory_source,
    parse_planner_payload,
    solution_name_from_source,
)

_PLAN_PROMPT = """You plan a COBOL→C# backend migration. Return ONE JSON object, no prose.

Do NOT map one COBOL file to one component. Group by behavior and CALL graph.
Do NOT invent a web UI. Do NOT schedule per-folder README files.
Documentation is exactly README.md and MIGRATION.md, last, after build/tests.

Inventory (compact — do not ask to re-read the repo):
{inventory}

JSON schema:
{{
  "summary": "<one line: N COBOL, copybooks, conversion units>",
  "solution_name": "{sln}",
  "work_items": [
    {{
      "work_item_id": "work-item-001",
      "title": "<domain name>",
      "kind": "conversion|persistence|cli|tests|documentation",
      "source_paths": ["relative COBOL/copybook paths"],
      "expected_paths": ["C# paths that WILL exist under the solution root"],
      "depends_on": ["work-item-ids this waits on"],
      "wave": 0
    }}
  ]
}}

expected_paths rules:
- conversion: src/Application/UseCases/{{Name}}/{{Name}}Handler.cs and I{{Name}}Port.cs
- persistence: src/Infrastructure/Persistence/*.cs
- cli: src/Cli/Program.cs
- tests: tests/Application.Tests/{{Name}}HandlerTests.cs
- documentation: only README.md and MIGRATION.md
- never .md except the documentation work item
- never frontend, app-here, or node paths
"""


def _inventory_blob(source_dir: Path, max_cobol_chars: int = 1200) -> str:
    files = inventory_source(source_dir)
    lines = []
    for f in files:
        extra = ""
        if f.program_id:
            extra = f" PROGRAM-ID={f.program_id} CALL={','.join(f.calls) or '-'}"
        lines.append(f"- {f.path} kind={f.kind} loc={f.loc}{extra}")
        if f.kind == "cobol_source":
            text = (source_dir / f.path).read_text(errors="replace")[:max_cobol_chars]
            lines.append("  excerpt:\n" + "\n".join("    " + ln for ln in text.splitlines()[:40]))
    return "\n".join(lines) if lines else "(empty)"


async def plan_repository(run_id: str, source_dir: Path) -> tuple[MigrationPlan, dict]:
    """Returns (plan, cost_meta). Always a valid plan — LLM failure uses fallback."""
    plan_id = str(ULID())
    sln = solution_name_from_source(source_dir)
    cost_meta = {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0, "source": "fallback"}
    prompt = _PLAN_PROMPT.format(inventory=_inventory_blob(source_dir), sln=sln)
    try:
        payload, cost_meta = await llm.plan_manifest(prompt, source_dir)
        cost_meta["source"] = "claude"
        plan = parse_planner_payload(payload, run_id, plan_id, sln)
        return plan, cost_meta
    except Exception:
        plan = fallback_plan(run_id, plan_id, source_dir)
        return plan, cost_meta
