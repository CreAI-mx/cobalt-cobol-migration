"""One-shot Claude Code planner. Reads a compact inventory (not the whole
estate) and returns a MigrationPlan. Falls back to work_items.fallback_plan.

Importers: orchestrator.py. API: POST /migration/{run_id}/plan.
User: un Claude Code analiza el repo una sola vez y devuelve un manifiesto.
"""
from __future__ import annotations

import json
from pathlib import Path

import aiosqlite
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
{exploration_section}
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

If the exploration section below is present:
- Assign `wave` ascending by risk_tier — every LOW-risk module's work items
  get a lower wave than any HIGH-risk module's, so low-complexity/low-risk
  code converts first (industry practice: start with low complexity, validate
  the toolchain, before touching risky modules).
- Reuse the listed business_rules verbatim as context for that module's
  conversion work item — they were already extracted, do not re-derive or
  contradict them.
"""


async def _load_locked_pack(conn: aiosqlite.Connection, run_id: str) -> dict | None:
    """Reads the LOCKED output of the isolated Exploration subsystem
    (routers/exploration.py, exploration_sessions.draft_pack_json) — the
    concrete "output of exploration is an input of the migration flow" wiring.
    Returns None if exploration was never run or not yet locked; the planner
    stays fully functional without it (exploration is optional)."""
    cursor = await conn.execute(
        "SELECT draft_pack_json FROM exploration_sessions WHERE run_id = ? AND status = 'LOCKED'",
        (run_id,),
    )
    row = await cursor.fetchone()
    if not row or not row[0]:
        return None
    try:
        return json.loads(row[0])
    except json.JSONDecodeError:
        return None


def _module_risk_tier(module: dict) -> str:
    risks = module.get("risks") or []
    return "HIGH" if any(
        r.upper().startswith("HIGH") or "COMP-3" in r.upper() or "REDEFINES" in r.upper()
        for r in risks
    ) else "LOW"


def _exploration_prompt_section(pack: dict | None) -> str:
    if not pack or not pack.get("modules"):
        return ""
    lines = ["\nLocked exploration pack (already analyzed — reuse, do not re-derive):"]
    for mod in pack["modules"]:
        tier = _module_risk_tier(mod)
        lines.append(
            f"- module {mod.get('module_id', '?')} risk_tier={tier} "
            f"members={mod.get('member_paths', [])}"
        )
        for rule in mod.get("business_rules", []):
            lines.append(f"    business_rule: {rule}")
        notes = mod.get("human_notes")
        if notes:
            lines.append(f"    human_notes: {notes}")
    baseline = pack.get("oracle_baseline") or {}
    if baseline:
        lines.append(
            "\nReal GnuCOBOL execution captured during Exploration (ground "
            "truth — the generated C# must reproduce this exact behavior, "
            "not a guess from reading the source alone):"
        )
        for path, result in baseline.items():
            status = "ok" if result.get("ok") else "FAILED TO RUN"
            lines.append(f"  - {path} ({status}):\n    {result.get('output', '')[:500]}")
    return "\n".join(lines) + "\n"


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


async def plan_repository(
    run_id: str, source_dir: Path, conn: aiosqlite.Connection | None = None,
) -> tuple[MigrationPlan, dict]:
    """Returns (plan, cost_meta). Always a valid plan — LLM failure uses fallback.
    conn is optional (backward compatible) — when given, a LOCKED exploration
    pack for this run_id enriches the prompt with risk tiers and business
    rules; when omitted or no locked pack exists, behaves exactly as before."""
    plan_id = str(ULID())
    sln = solution_name_from_source(source_dir)
    cost_meta = {"cost_usd": 0.0, "input_tokens": 0, "output_tokens": 0, "latency_ms": 0, "source": "fallback"}
    pack = await _load_locked_pack(conn, run_id) if conn is not None else None
    prompt = _PLAN_PROMPT.format(
        inventory=_inventory_blob(source_dir), sln=sln,
        exploration_section=_exploration_prompt_section(pack),
    )
    try:
        payload, cost_meta = await llm.plan_manifest(prompt, source_dir)
        cost_meta["source"] = "claude"
        plan = parse_planner_payload(payload, run_id, plan_id, sln)
        return plan, cost_meta
    except Exception:
        plan = fallback_plan(run_id, plan_id, source_dir)
        return plan, cost_meta
