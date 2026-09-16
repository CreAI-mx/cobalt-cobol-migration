"""Regression tests for orchestrator.execute_migration()'s unified
Build->Test->Parity verify-then-repair loop — the exact behavior verified
this session only via real, expensive, live end-to-end migration runs
(multiple real LLM calls, real dotnet/cobc). These tests reproduce the same
control-flow guarantees with zero real subprocess calls, so a regression is
caught for free instead of needing another live run + human to notice.

Two real bugs this session, both covered here:
1. A single repair_attempts counter shared across Build/Test/Parity meant an
   early transient failure (e.g. a build timeout) could burn the whole
   MAX_RETRY budget, leaving zero attempts for a later, unrelated, genuinely
   fixable bug in a different gate. Fixed with a per-stage budget dict.
2. The repair agent can Write a correct fix to disk and then still crash
   before returning its JSON result envelope — treating that as "the fix
   failed" and giving up immediately was wrong; the chain must always
   re-verify before deciding an attempt was wasted.

Importers: pytest. No real subprocess, no real LLM call, no real dotnet/cobc.
"""
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import aiosqlite
import pytest

import db as db_module
import orchestrator
from llm import ConversionResult, HeadlessInvocationError
from work_items import MigrationPlan, WorkItem

SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "migration-state" / "schema.sql"


async def _make_conn() -> aiosqlite.Connection:
    """migration_plans/work_items/etc. are NOT in schema.sql — they're created
    by db.py's in-code migrations (_migrate_work_items and friends), the same
    ones init_db() runs against the real DB_PATH. Mirror that here against an
    in-memory connection instead of monkeypatching DB_PATH."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.executescript(SCHEMA_PATH.read_text())
    await conn.commit()
    await db_module._migrate_file_kind(conn)
    await db_module._migrate_suggested_component_name(conn)
    await db_module._migrate_gate_decisions(conn)
    await db_module._migrate_architecture_decisions(conn)
    await db_module._migrate_run_events(conn)
    await db_module._migrate_work_items(conn)
    return conn


async def _insert_run_stub(conn: aiosqlite.Connection, run_id: str) -> None:
    """work_items/migration_plans/cost_logs all FK to migration_runs(run_id)."""
    await conn.execute(
        "INSERT INTO migration_runs (run_id, started_at, status, source_repo, target_lang) "
        "VALUES (?, ?, 'RUNNING', 'test', 'csharp')",
        (run_id, "2026-01-01T00:00:00Z"),
    )
    await conn.commit()


def _completed_plan(run_id: str) -> MigrationPlan:
    """A plan where every real work item is already 'completed' — the
    Generating loop's ready_items() returns nothing, so execute_migration()
    falls straight through to the Building phase, matching a resumed run."""
    items = [
        WorkItem(
            work_item_id=f"{run_id}:work-item-001", slug="work-item-001",
            title="Persistence", kind="persistence", status="completed",
            expected_paths=["src/Infrastructure/Persistence/README.md"],
        ),
        WorkItem(
            work_item_id=f"{run_id}:work-item-002", slug="work-item-002",
            title="Docs", kind="documentation", status="completed",
            expected_paths=["README.md", "docs/MIGRATION.md"],
        ),
    ]
    return MigrationPlan(
        plan_id=f"plan-{run_id}", run_id=run_id, summary="test plan",
        solution_name="TestSolution", work_items=items, stage="pending",
    )


async def _run_with_mocks(monkeypatch, tmp_path: Path, run_id: str, plan: MigrationPlan,
                          dotnet_side_effect, parity_side_effect,
                          repair_csharp_mock=None, repair_test_mock=None, repair_parity_mock=None):
    monkeypatch.setattr(orchestrator, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(orchestrator, "ensure_plan", AsyncMock(return_value=plan))
    monkeypatch.setattr(orchestrator, "_dotnet", AsyncMock(side_effect=dotnet_side_effect))
    monkeypatch.setattr(orchestrator.parity_gate, "run_parity_gate", AsyncMock(side_effect=parity_side_effect))
    ok_result = ConversionResult(files_written=[], cost_usd=0.0, input_tokens=0, output_tokens=0, latency_ms=0)
    monkeypatch.setattr(orchestrator.llm, "repair_csharp",
                        repair_csharp_mock or AsyncMock(return_value=ok_result))
    monkeypatch.setattr(orchestrator.llm, "repair_test_failure",
                        repair_test_mock or AsyncMock(return_value=ok_result))
    monkeypatch.setattr(orchestrator.llm, "repair_parity_mismatch",
                        repair_parity_mock or AsyncMock(return_value=ok_result))

    conn = await _make_conn()
    await _insert_run_stub(conn, run_id)
    events: list = []
    try:
        await orchestrator.execute_migration(run_id, conn, events)
    finally:
        await conn.close()
    return events


def test_build_exhausts_its_own_budget_without_touching_parity(monkeypatch, tmp_path):
    """Real bug fixed this session: Build failing repeatedly must consume ONLY
    Build's own retry budget. Parity must never be attempted (it comes after
    Build in the chain) and its repair function must never be called."""
    plan = _completed_plan("run-build-exhausted")
    parity_mock = AsyncMock()

    async def dotnet_always_fails(cmd, cwd, timeout=120):
        return False, "simulated persistent compile error"

    events = asyncio.run(_run_with_mocks(
        monkeypatch, tmp_path, "run-build-exhausted", plan,
        dotnet_side_effect=dotnet_always_fails,
        parity_side_effect=parity_mock,
    ))

    blocked = [e for e in events if getattr(e, "phase", None) == "Building" and e.status == "BLOCKED"]
    assert blocked, "Building must end BLOCKED when it never succeeds"
    parity_mock.assert_not_called()
    assert not any(getattr(e, "phase", None) == "Parity Validation" for e in events)


def test_build_and_parity_have_independent_retry_budgets(monkeypatch, tmp_path):
    """Real bug fixed this session: a single shared repair_attempts counter
    meant Build's own (successful) repair could exhaust the budget Parity
    needed for its own, unrelated, later failure. Build fails once then
    succeeds (1 repair call) — Parity must still get its own full 2 attempts,
    not share/inherit Build's spent budget."""
    plan = _completed_plan("run-independent-budgets")
    build_calls = {"n": 0}

    async def dotnet_fails_once_then_succeeds(cmd, cwd, timeout=120):
        build_calls["n"] += 1
        return (build_calls["n"] > 1), "compile error" if build_calls["n"] == 1 else "ok"

    async def parity_always_fails(conn, run_id, plan_, source_dir, csharp, events):
        return False, "1/1 programs match\n\nsimulated persistent mismatch"

    repair_csharp_mock = AsyncMock(return_value=ConversionResult(
        files_written=[], cost_usd=0.0, input_tokens=0, output_tokens=0, latency_ms=0))
    repair_parity_mock = AsyncMock(return_value=ConversionResult(
        files_written=[], cost_usd=0.0, input_tokens=0, output_tokens=0, latency_ms=0))

    asyncio.run(_run_with_mocks(
        monkeypatch, tmp_path, "run-independent-budgets", plan,
        dotnet_side_effect=dotnet_fails_once_then_succeeds,
        parity_side_effect=parity_always_fails,
        repair_csharp_mock=repair_csharp_mock,
        repair_parity_mock=repair_parity_mock,
    ))

    assert repair_csharp_mock.call_count == 1, (
        "Build succeeded after exactly one repair — its budget must show exactly 1 call, "
        "not be starved or over-consumed by Parity's separate failures"
    )
    assert repair_parity_mock.call_count == 2, (
        "Parity gets its own full MAX_RETRY=2 budget, independent of Build's 1 call"
    )


def test_repair_agent_crash_does_not_abort_the_loop(monkeypatch, tmp_path):
    """Real bug fixed this session: the repair agent can Write a correct fix
    to disk and then still crash before returning its JSON envelope. The old
    code treated that HeadlessInvocationError as fatal and broke immediately
    — the fix must always re-verify (call _dotnet again) instead of giving up
    on the first crash, only stopping once the per-stage budget is truly
    exhausted."""
    plan = _completed_plan("run-repair-crash")
    build_calls = {"n": 0}

    async def dotnet_build_fails_then_succeeds(cmd, cwd, timeout=120):
        # scaffold_solution() creates a real Tests.csproj, so Testing also
        # calls this same _dotnet() with cmd[0] == "test" — only count/gate
        # on "build" calls, a real "dotnet test" run is a separate concern.
        if cmd[0] != "build":
            return True, "dotnet test ok"
        build_calls["n"] += 1
        # First build call: real failure. Second (after the crashed repair
        # attempt): the fix landed on disk before the crash, so it passes.
        return (build_calls["n"] > 1), "compile error"

    async def parity_ok(conn, run_id, plan_, source_dir, csharp, events):
        return True, "0/0 programs match"

    crash_then_ok = AsyncMock(side_effect=[HeadlessInvocationError("simulated crash after Write")])

    events = asyncio.run(_run_with_mocks(
        monkeypatch, tmp_path, "run-repair-crash", plan,
        dotnet_side_effect=dotnet_build_fails_then_succeeds,
        parity_side_effect=parity_ok,
        repair_csharp_mock=crash_then_ok,
    ))

    assert build_calls["n"] == 2, "must re-verify (call _dotnet build again) after the repair agent crashed"
    passed = [e for e in events if getattr(e, "phase", None) == "__done__"]
    assert passed, "pipeline must reach a terminal state, not hang or crash the whole run"
    build_ok = [e for e in events if getattr(e, "phase", None) == "Building" and e.status == "OK"]
    assert build_ok, "Building must end OK — the crash-before-envelope repair attempt still fixed it"
