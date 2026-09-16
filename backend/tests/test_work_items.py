"""Unit tests for MigrationPlan / WorkItem state machine and fallback manifesto.

Importers: pytest. No HTTP. User: pruebas unitarias para planificación y estados.
"""
from pathlib import Path

import pytest

from work_items import (
    fallback_plan,
    inventory_source,
    parse_planner_payload,
    progress_of,
    ready_concurrency,
    ready_items,
    transition,
)


def test_transition_happy_path():
    assert transition("pending", "generating") == "generating"
    assert transition("generating", "completed") == "completed"
    assert transition("failed", "generating") == "generating"


def test_transition_rejects_skip():
    with pytest.raises(ValueError):
        transition("pending", "completed")
    with pytest.raises(ValueError):
        transition("completed", "generating")


def test_concurrency_is_min_of_ready_and_cap(monkeypatch):
    monkeypatch.setenv("COBALT_MAX_AGENTS", "3")
    assert ready_concurrency(1) == 1
    assert ready_concurrency(8) == 3
    assert ready_concurrency(8, limit=2) == 2


def _cobol(dir: Path, name: str, pid: str, calls: list[str] | None = None) -> None:
    body = f"       IDENTIFICATION DIVISION.\n       PROGRAM-ID. {pid}.\n"
    for c in calls or []:
        body += f"           CALL '{c}'\n"
    (dir / name).write_text(body)


def test_fallback_groups_call_graph_not_one_file_one_item(tmp_path: Path):
    src = tmp_path / "estate"
    src.mkdir()
    _cobol(src, "main.cob", "Main", ["DataProgram", "Operations"])
    _cobol(src, "data.cob", "DataProgram")
    _cobol(src, "operations.cob", "Operations", ["DataProgram"])
    (src / "README.md").write_text("# docs")
    plan = fallback_plan("run1", "plan1", src)
    conversions = [w for w in plan.work_items if w.kind == "conversion"]
    assert len(conversions) == 1
    assert len(conversions[0].source_paths) == 3
    kinds = {w.kind for w in plan.work_items}
    assert "cli" in kinds
    assert "documentation" in kinds
    docs = next(w for w in plan.work_items if w.kind == "documentation")
    assert docs.expected_paths == ["README.md", "docs/MIGRATION.md"]
    # 2026-09-15: one README.md per leaf folder actually touched (user: "un
    # md por carpeta en la ultima capa") — a conversion item can span several
    # leaf folders when call-graph grouping merges multiple COBOL programs
    # into one work item (one README per program folder, not per work item),
    # while persistence/cli only ever touch a single folder each.
    conv = next(w for w in plan.work_items if w.kind == "conversion")
    conv_mds = [p for p in conv.expected_paths if p.lower().endswith(".md")]
    assert len(conv_mds) == len(conv.source_paths)
    assert all(p.endswith("/README.md") for p in conv_mds)
    # "tests" work items never carried a README requirement — only
    # conversion/persistence/cli (code-authoring kinds) do.
    for w in plan.work_items:
        if w.kind in ("conversion", "documentation", "tests"):
            continue
        md_paths = [p for p in w.expected_paths if p.lower().endswith(".md")]
        assert len(md_paths) == 1
        assert md_paths[0].endswith("/README.md") or md_paths[0] == "README.md"
    prog = progress_of(plan)
    assert prog["work_items_total"] == len(plan.work_items)
    assert prog["percent"] == 0


def test_disconnected_cobol_become_separate_units(tmp_path: Path):
    src = tmp_path / "estate"
    src.mkdir()
    _cobol(src, "a.cob", "Alpha")
    _cobol(src, "b.cob", "Beta")
    plan = fallback_plan("run1", "plan1", src)
    conversions = [w for w in plan.work_items if w.kind == "conversion"]
    assert len(conversions) == 2


def test_planner_payload_strips_extra_markdown_and_traversal():
    payload = {
        "summary": "demo",
        "solution_name": "LedgerSystem",
        "work_items": [
            {
                "work_item_id": "work-item-001",
                "title": "Lookup",
                "kind": "conversion",
                "source_paths": ["data.cob", "../etc/passwd"],
                "expected_paths": [
                    "LedgerSystem.Application/UseCases/Lookup/LookupHandler.cs",
                    "sneaky/README.md",
                    "../../escape.cs",
                ],
            },
            {
                "work_item_id": "work-item-002",
                "title": "Docs",
                "kind": "documentation",
                "expected_paths": ["README.md", "docs/MIGRATION.md", "docs/GRAPH.md"],
            },
        ],
    }
    plan = parse_planner_payload(payload, "run1", "plan1", "LedgerSystem")
    conv = plan.work_items[0]
    assert conv.source_paths == ["data.cob"]
    # "sneaky/README.md" (wrong folder, LLM-proposed) is dropped; the real
    # README.md is derived from the item's own code paths instead (2026-09-15
    # fix) — never an LLM-supplied path outside its own leaf folder.
    assert conv.expected_paths == [
        "LedgerSystem.Application/UseCases/Lookup/LookupHandler.cs",
        "LedgerSystem.Application/UseCases/Lookup/README.md",
    ]
    docs = plan.work_items[1]
    assert docs.expected_paths == ["README.md", "docs/MIGRATION.md"]


def test_ready_items_honor_depends_on(tmp_path: Path):
    src = tmp_path / "e"
    src.mkdir()
    _cobol(src, "a.cob", "A")
    plan = fallback_plan("r", "p", src)
    ready = ready_items(plan)
    assert all(not w.depends_on for w in ready)
    first = next(w for w in plan.work_items if w.kind == "conversion")
    first.status = "completed"
    ready2 = ready_items(plan)
    assert any(w.kind == "cli" for w in ready2)


def test_inventory_skips_hidden(tmp_path: Path):
    src = tmp_path / "e"
    src.mkdir()
    _cobol(src, "a.cob", "A")
    (src / ".git").mkdir()
    (src / ".git" / "config").write_text("x")
    files = inventory_source(src)
    assert all(not f.path.startswith(".") for f in files)
    assert any(f.path.endswith("a.cob") for f in files)


def test_solution_name_does_not_double_system_suffix(tmp_path: Path):
    # Real defect found 2026-09-15: a source folder ending in the plural
    # "systems" (not singular "system") slipped past the singular-only
    # endswith("system") guard, producing "CobolBankingSystemsSystem".
    from work_items import solution_name_from_source

    plural = tmp_path / "cobol-banking-systems"
    plural.mkdir()
    assert solution_name_from_source(tmp_path) in {"CobolBankingSystems"}

    singular = tmp_path / "singular-only"
    (singular).mkdir(exist_ok=True)
    plain = tmp_path.parent / "plain-estate"
    plain.mkdir(exist_ok=True)
    (plain / "ledger").mkdir()
    assert solution_name_from_source(plain) == "LedgerSystem"


def test_fallback_plan_emits_real_tests_work_items(tmp_path: Path):
    # Real defect found 2026-09-15 (run 01M2KPAMSM89P30VCHGFD7C9MY): this
    # function never emitted a "tests" work item at all, so the scaffolded
    # *.Tests.csproj stayed empty and `dotnet test` silently "passed" with
    # zero [Fact] methods ever written.
    src = tmp_path / "estate"
    src.mkdir()
    _cobol(src, "a.cob", "AccountLookup")
    _cobol(src, "b.cob", "AmlFlagging")
    plan = fallback_plan("run1", "plan1", src)
    tests_items = [w for w in plan.work_items if w.kind == "tests"]
    assert len(tests_items) == 2
    conv_slugs = {w.slug for w in plan.work_items if w.kind == "conversion"}
    for t in tests_items:
        assert t.depends_on and t.depends_on[0] in conv_slugs
        assert all(p.endswith("HandlerTests.cs") for p in t.expected_paths)
