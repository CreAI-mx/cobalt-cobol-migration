"""MigrationPlan + WorkItem domain — single source of truth for orchestrator,
SQLite, REST, and the circumstantial UI.

Importers: orchestrator.py, planner.py, routers/pipeline.py, tests/test_work_items.py.
API: GET/POST /migration/{run_id}/plan. Schema: migration_plans, work_items,
work_item_artifacts.
User: "la uid debe ser si o si agentica flexible circusntancial" + manifiesto
real, no un COBOL = un componente, no 46 placeholders.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

WorkItemStatus = Literal[
    "pending",
    "analyzing",
    "generating",
    "building",
    "testing",
    "completed",
    "failed",
]
WorkItemKind = Literal[
    "conversion",
    "persistence",
    "cli",
    "tests",
    "documentation",
]
UiBlockType = Literal[
    "work_item_list",
    "active_agents",
    "build_gate",
    "test_gate",
    "download",
    "decision_required",
]

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"analyzing", "generating", "failed"},
    "analyzing": {"generating", "failed", "pending"},
    "generating": {"building", "testing", "completed", "failed", "pending"},
    "building": {"testing", "completed", "failed", "pending"},
    "testing": {"completed", "failed", "pending"},
    "completed": set(),
    "failed": {"generating", "building", "pending"},  # retry of the failed unit only
}
# "X" -> "pending" (X != completed) is not a normal forward step — it is
# specifically for orphan recovery: a fresh process starting up can find a work
# item stuck in a transient state with no live task behind it (the previous
# process died mid-item — server restart, crash) and needs to make it eligible
# for ready_items() again. Real defect this fixes (2026-09-15, run
# 01M2KM41FKP2V5Y38628VCWYRC): an item orphaned in "generating" was invisible
# to ready_items() forever, so the pipeline finished Build/Test/Docs and
# reported PASSED with that item's file missing or truncated.
# "failed" -> "pending" is the same recovery, for a genuinely exhausted item: a
# user-triggered retry of a FAILED run (POST /start again) must resume from
# where the run stopped, not from zero (user, 2026-09-15: retries must be
# agentic/automatic "desde donde quedo", never a full restart) — so
# execute_migration() revives "failed" items (and zeroes retry_count) on a
# fresh entry, same as the transient-state items above.

PROGRAM_ID_RE = re.compile(r"PROGRAM-ID\.\s*([A-Za-z0-9_-]+)", re.IGNORECASE)
CALL_RE = re.compile(r"CALL\s+[\"']([A-Za-z0-9_-]+)[\"']", re.IGNORECASE)
IO_HINT_RE = re.compile(
    r"\b(SELECT|ASSIGN|VSAM|ORGANIZATION|FD\s+|OPEN\s+I-O|WRITE\s+)\b",
    re.IGNORECASE,
)
SAFE_REL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")

MAX_RETRY = 2


def max_agent_slots() -> int:
    """Configurable concurrency — never a magic number in the orchestrator."""
    raw = os.environ.get("COBALT_MAX_AGENTS", "3")
    try:
        n = int(raw)
    except ValueError:
        n = 3
    return max(1, min(n, 8))


def transition(current: str, nxt: str) -> str:
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if nxt not in allowed:
        raise ValueError(f"illegal WorkItem status {current!r} → {nxt!r}")
    return nxt


def ready_concurrency(ready_count: int, limit: int | None = None) -> int:
    cap = limit if limit is not None else max_agent_slots()
    return min(max(ready_count, 0), cap)


@dataclass
class SourceFile:
    path: str
    kind: str
    program_id: str | None = None
    loc: int = 0
    sha256: str = ""
    calls: list[str] = field(default_factory=list)


@dataclass
class WorkItem:
    work_item_id: str
    slug: str
    title: str
    kind: WorkItemKind
    status: WorkItemStatus = "pending"
    source_paths: list[str] = field(default_factory=list)
    expected_paths: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    wave: int = 0
    retry_count: int = 0
    workspace_rel: str = ""
    agent_id: str | None = None
    error: str | None = None
    artifacts: list["WorkItemArtifact"] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "work_item_id": self.work_item_id,
            "slug": self.slug,
            "title": self.title,
            "kind": self.kind,
            "status": self.status,
            "source_paths": self.source_paths,
            "expected_paths": self.expected_paths,
            "depends_on": self.depends_on,
            "wave": self.wave,
            "retry_count": self.retry_count,
            "workspace_rel": self.workspace_rel,
            "agent_id": self.agent_id,
            "error": self.error,
            "artifact_count": len(self.artifacts),
        }


@dataclass
class WorkItemArtifact:
    artifact_id: str
    work_item_id: str
    declared_path: str
    sha256: str
    integrated: bool = False


@dataclass
class UiBlock:
    type: UiBlockType
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"type": self.type, **self.payload}


@dataclass
class MigrationPlan:
    plan_id: str
    run_id: str
    summary: str
    solution_name: str
    work_items: list[WorkItem]
    ui_blocks: list[UiBlock] = field(default_factory=list)
    stage: str = "pending"

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "run_id": self.run_id,
            "summary": self.summary,
            "solution_name": self.solution_name,
            "stage": self.stage,
            "work_items": [w.to_dict() for w in self.work_items],
            "ui_blocks": [b.to_dict() for b in self.ui_blocks],
            "progress": progress_of(self),
        }


def progress_of(plan: MigrationPlan) -> dict:
    items = plan.work_items
    expected = [p for w in items for p in w.expected_paths]
    done_items = sum(1 for w in items if w.status == "completed")
    failed = sum(1 for w in items if w.status == "failed")
    integrated = sum(1 for w in items for a in w.artifacts if a.integrated)
    return {
        "work_items_done": done_items,
        "work_items_total": len(items),
        "work_items_failed": failed,
        "artifacts_integrated": integrated,
        "artifacts_expected": len(expected),
        "percent": int(round(100 * done_items / len(items))) if items else 0,
    }


def compose_ui_blocks(plan: MigrationPlan, *, live: bool, build_ok: bool | None,
                      test_ok: bool | None, downloadable: bool) -> list[UiBlock]:
    """Circumstantial UI: only blocks that the current facts justify."""
    blocks: list[UiBlock] = [
        UiBlock("work_item_list", {"count": len(plan.work_items)}),
    ]
    active = [w for w in plan.work_items if w.status in {"analyzing", "generating", "building", "testing"}]
    if active:
        blocks.append(UiBlock("active_agents", {
            "agents": [
                {"work_item_id": w.work_item_id, "title": w.title, "status": w.status,
                 "agent_id": w.agent_id}
                for w in active
            ],
        }))
    if plan.stage in {"building", "testing", "completed", "failed"} or build_ok is not None:
        blocks.append(UiBlock("build_gate", {
            "ok": build_ok,
            "open": plan.stage == "building" or build_ok is False,
        }))
    if plan.stage in {"testing", "completed", "failed"} or test_ok is not None:
        blocks.append(UiBlock("test_gate", {
            "ok": test_ok,
            "open": plan.stage == "testing" or test_ok is False,
        }))
    if downloadable:
        blocks.append(UiBlock("download", {"href": f"/migration/{plan.run_id}/artifact.zip"}))
    failed = [w for w in plan.work_items if w.status == "failed"]
    if failed and not live:
        blocks.append(UiBlock("decision_required", {
            "reason": "retry_failed_units",
            "work_item_ids": [w.work_item_id for w in failed],
        }))
    return blocks


def pascal_stem(name: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", name)
    return "".join(p[:1].upper() + p[1:].lower() for p in parts if p)


def solution_name_from_source(source_dir: Path) -> str:
    dirs = [p for p in source_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
    raw = dirs[0].name if dirs else "Accounting"
    raw = re.sub(r"^(node|react|vue|angular|next|frontend|web|ui|client)[-._]*", "", raw, flags=re.I)
    raw = re.sub(r"[-._]*(app|application|frontend|webapp|web|ui|client|spa|gui)$", "", raw, flags=re.I)
    pascal = pascal_stem(raw)
    if not pascal or pascal.lower() in {"app", "web", "ui", "client", "node"}:
        pascal = "Accounting"
    # Real defect found 2026-09-15: a source folder named "cobol-banking-
    # systems" (plural) produced pascal_stem "CobolBankingSystems", which does
    # NOT match the singular endswith("system") check below, so "System" got
    # appended anyway -> "CobolBankingSystemsSystem". Check both forms.
    return pascal if pascal.lower().endswith(("system", "systems")) else f"{pascal}System"


def classify_kind(rel: str) -> str:
    lower = rel.lower()
    if lower.endswith((".cpy", ".copy", ".cpb")):
        return "copybook"
    if lower.endswith((".cbl", ".cob", ".cobol", ".pco")):
        return "cobol_source"
    if lower.endswith((".md", ".txt", ".rst")):
        return "doc"
    return "other"


def inventory_source(source_dir: Path) -> list[SourceFile]:
    files: list[SourceFile] = []
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(source_dir)).replace("\\", "/")
        if any(part.startswith(".") for part in Path(rel).parts):
            continue
        raw = path.read_bytes()
        text = raw.decode(errors="replace")
        kind = classify_kind(rel)
        pid = None
        calls: list[str] = []
        if kind == "cobol_source":
            m = PROGRAM_ID_RE.search(text)
            pid = m.group(1) if m else None
            calls = CALL_RE.findall(text)
        files.append(SourceFile(
            path=rel, kind=kind, program_id=pid, loc=len(text.splitlines()),
            sha256=hashlib.sha256(raw).hexdigest(), calls=calls,
        ))
    return files


def connected_cobol_groups(files: list[SourceFile]) -> list[list[SourceFile]]:
    cobol = [f for f in files if f.kind == "cobol_source"]
    if not cobol:
        return []
    pid_to = {f.program_id.upper(): f for f in cobol if f.program_id}
    parent: dict[str, str] = {f.path: f.path for f in cobol}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for f in cobol:
        for target in f.calls:
            other = pid_to.get(target.upper())
            if other and other.path != f.path:
                union(f.path, other.path)
    groups: dict[str, list[SourceFile]] = {}
    by_path = {f.path: f for f in cobol}
    for f in cobol:
        groups.setdefault(find(f.path), []).append(by_path[f.path])
    return [sorted(g, key=lambda x: x.path) for g in groups.values()]


def _handler_paths(sln: str, name: str) -> list[str]:
    # sln is unused here for paths (2026-09-15: nested src/ layout replaced
    # flat "{sln}.Layer/" folders — user: "odia esa jerarquia de puntos") but
    # kept as a parameter since C# namespaces still use it; do not remove.
    del sln
    return [
        f"src/Application/UseCases/{name}/{name}Handler.cs",
        f"src/Application/UseCases/{name}/I{name}Port.cs",
    ]


def _title_for_group(group: list[SourceFile]) -> str:
    names = [pascal_stem(f.program_id or Path(f.path).stem) for f in group]
    if len(names) == 1:
        return names[0]
    return " + ".join(names[:3])


def fallback_plan(run_id: str, plan_id: str, source_dir: Path,
                  files: list[SourceFile] | None = None) -> MigrationPlan:
    """Deterministic manifesto when the planner LLM is unavailable.
    Groups COBOL by CALL graph — never 1 file = 1 work item unless they
    are actually disconnected."""
    files = files if files is not None else inventory_source(source_dir)
    sln = solution_name_from_source(source_dir)
    copybooks = [f.path for f in files if f.kind == "copybook"]
    groups = connected_cobol_groups(files)
    items: list[WorkItem] = []
    conversion_ids: list[str] = []

    for i, group in enumerate(groups, start=1):
        slug = f"work-item-{i:03d}"
        expected: list[str] = []
        for src in group:
            name = pascal_stem(src.program_id or Path(src.path).stem)
            expected.extend(_handler_paths(sln, name))
            # One short README per leaf use-case folder — user 2026-09-15: "un
            # md por carpeta en la ultima capa, breve, no una cantidad grande."
            expected.append(f"src/Application/UseCases/{name}/README.md")
        seen: set[str] = set()
        expected = [p for p in expected if not (p in seen or seen.add(p))]
        sources = [f.path for f in group] + copybooks
        item = WorkItem(
            work_item_id=slug, slug=slug, title=_title_for_group(group),
            kind="conversion", source_paths=sources, expected_paths=expected,
            wave=0, workspace_rel=f"workspaces/{slug}",
        )
        items.append(item)
        conversion_ids.append(slug)

    # Real defect found 2026-09-15 (run 01M2KPAMSM89P30VCHGFD7C9MY): this
    # function never emitted a "tests" work item at all — only the LLM
    # planner path did. scaffold_solution() still creates an empty
    # *.Tests.csproj, so `dotnet test` exits 0 with zero [Fact] methods and
    # the pipeline reported "Testing OK — tests passed" with nothing real
    # having run. One tests item per conversion group, mirroring the real
    # handler/port paths it must exercise.
    n = len(items) + 1
    for i, group in enumerate(groups, start=1):
        conv_slug = f"work-item-{i:03d}"
        names = [pascal_stem(src.program_id or Path(src.path).stem) for src in group]
        test_slug = f"work-item-{n:03d}"
        items.append(WorkItem(
            work_item_id=test_slug, slug=test_slug,
            title=f"{_title_for_group(group)} tests", kind="tests",
            source_paths=[f.path for f in group] + copybooks,
            expected_paths=[
                f"tests/Application.Tests/{name}HandlerTests.cs" for name in names
            ],
            depends_on=[conv_slug], wave=1,
            workspace_rel=f"workspaces/{test_slug}",
        ))
        n += 1
    if any(IO_HINT_RE.search(Path(source_dir, f.path).read_text(errors="replace"))
           for f in files if f.kind == "cobol_source"):
        slug = f"work-item-{n:03d}"
        items.append(WorkItem(
            work_item_id=slug, slug=slug, title="Persistence adapter",
            kind="persistence",
            source_paths=[f.path for f in files if f.kind == "cobol_source"],
            expected_paths=[
                "src/Infrastructure/Persistence/FileLedgerStore.cs",
                "src/Infrastructure/Persistence/README.md",
            ],
            depends_on=list(conversion_ids), wave=1,
            workspace_rel=f"workspaces/{slug}",
        ))
        n += 1

    cli_slug = f"work-item-{n:03d}"
    items.append(WorkItem(
        work_item_id=cli_slug, slug=cli_slug, title="CLI host",
        kind="cli",
        source_paths=[f.path for f in files if f.kind == "cobol_source"][:1],
        expected_paths=[
            "src/Cli/Program.cs", "src/Cli/README.md",
            "src/Cli/parity-manifest.json",
        ],
        depends_on=list(conversion_ids), wave=1,
        workspace_rel=f"workspaces/{cli_slug}",
    ))
    n += 1

    doc_slug = f"work-item-{n:03d}"
    items.append(WorkItem(
        work_item_id=doc_slug, slug=doc_slug, title="Documentation",
        kind="documentation",
        source_paths=[],
        expected_paths=["README.md", "docs/MIGRATION.md"],
        depends_on=[cli_slug], wave=3,
        workspace_rel=f"workspaces/{doc_slug}",
    ))

    cobol_n = sum(1 for f in files if f.kind == "cobol_source")
    cpy_n = len(copybooks)
    summary = (
        f"{cobol_n} COBOL program{'s' if cobol_n != 1 else ''}"
        f"{', ' + str(cpy_n) + ' copybook' if cpy_n else ''}, "
        f"{len(groups)} conversion unit{'s' if len(groups) != 1 else ''}"
    )
    plan = MigrationPlan(
        plan_id=plan_id, run_id=run_id, summary=summary, solution_name=sln,
        work_items=items, stage="pending",
    )
    plan.ui_blocks = compose_ui_blocks(
        plan, live=False, build_ok=None, test_ok=None, downloadable=False,
    )
    return plan


def parse_planner_payload(payload: dict, run_id: str, plan_id: str, sln: str) -> MigrationPlan:
    """Validate planner JSON. Reject extra markdown, path traversal, empty plans."""
    items_raw = payload.get("work_items") or []
    if not isinstance(items_raw, list) or not items_raw:
        raise ValueError("planner returned no work_items")
    items: list[WorkItem] = []
    slugs: set[str] = set()
    for i, raw in enumerate(items_raw, start=1):
        if not isinstance(raw, dict):
            raise ValueError(f"work_item {i} is not an object")
        slug = str(raw.get("work_item_id") or raw.get("slug") or f"work-item-{i:03d}")
        if slug in slugs:
            raise ValueError(f"duplicate work_item_id {slug}")
        slugs.add(slug)
        kind = str(raw.get("kind") or "conversion")
        if kind not in {"conversion", "persistence", "cli", "tests", "documentation"}:
            kind = "conversion"
        expected = [p.replace("\\", "/") for p in (raw.get("expected_paths") or [])]
        expected = [p for p in expected if SAFE_REL.match(p) and ".." not in p]
        if kind == "documentation":
            expected = [p for p in expected if p in {"README.md", "docs/MIGRATION.md"}]
            if not expected:
                expected = ["README.md", "docs/MIGRATION.md"]
        else:
            # Allow exactly one short README.md per work item's own leaf folder
            # (2026-09-15: "un md por carpeta en la ultima capa, breve"). Derive
            # the folder from this item's own .cs paths, not whatever .md path
            # the LLM may have proposed, so it can't point outside its folder.
            code_paths = [p for p in expected if not p.lower().endswith(".md")]
            folders = {str(Path(p).parent) for p in code_paths if "/" in p}
            expected = code_paths + [f"{f}/README.md" for f in sorted(folders)[:1]]
            # Real defect found 2026-09-15 (run 01M2KWNDBMFCVYDXEAT82FTJRN): the
            # parity-manifest.json contract was only force-added in
            # fallback_plan(), never here — the planner-LLM path (this
            # function) is what actually ran, so the CLI work item's
            # expected_paths never included it, the LLM never wrote it, and
            # every program in the parity gate came back
            # NO_INVOCATION_CONTRACT. Force it the same way README.md is
            # forced above, not left to prompt compliance.
            if kind == "cli":
                expected.append("src/Cli/parity-manifest.json")
        if not expected:
            raise ValueError(f"{slug} has no safe expected_paths")
        sources = [p.replace("\\", "/") for p in (raw.get("source_paths") or [])]
        sources = [p for p in sources if SAFE_REL.match(p) and ".." not in p]
        items.append(WorkItem(
            work_item_id=slug, slug=slug,
            title=str(raw.get("title") or slug),
            kind=kind,  # type: ignore[arg-type]
            source_paths=sources, expected_paths=expected,
            depends_on=[str(d) for d in (raw.get("depends_on") or [])],
            wave=int(raw.get("wave") or 0),
            workspace_rel=f"workspaces/{slug}",
        ))
    summary = str(payload.get("summary") or f"{len(items)} work items")
    plan = MigrationPlan(
        plan_id=plan_id, run_id=run_id, summary=summary,
        solution_name=str(payload.get("solution_name") or sln),
        work_items=items, stage="pending",
    )
    plan.ui_blocks = compose_ui_blocks(
        plan, live=False, build_ok=None, test_ok=None, downloadable=False,
    )
    return plan


def ready_items(plan: MigrationPlan) -> list[WorkItem]:
    # slug, not work_item_id: depends_on always stores bare slugs (both
    # fallback_plan and parse_planner_payload build it that way), but
    # work_item_id becomes "{run_id}:{slug}" once a plan round-trips through
    # persist_plan/load_plan (PK-collision fix, 2026-09-15). Comparing against
    # work_item_id here meant a dependent item's deps NEVER matched post-DB,
    # so persistence/cli work items could never become ready again after any
    # retry or process restart. slug is never touched by that fix.
    done = {w.slug for w in plan.work_items if w.status == "completed"}
    out: list[WorkItem] = []
    for w in plan.work_items:
        if w.status != "pending":
            continue
        if all(dep in done for dep in w.depends_on):
            out.append(w)
    return out


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assert_safe_rel(rel: str) -> str:
    rel = rel.replace("\\", "/").lstrip("/")
    if ".." in rel or not SAFE_REL.match(rel):
        raise ValueError(f"unsafe path {rel!r}")
    return rel
