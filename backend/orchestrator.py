"""Work-item orchestrator: FastAPI is the foreman, Claude Code the engineer.

Importers: routers/pipeline.py. API: POST /start, GET /plan, GET /artifact.zip.
Schema: migration_plans, work_items, work_item_artifacts.
User: workers aislados, integrador con hash, build/test/repair, reanudación,
UI sobre unidades reales.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite
from ulid import ULID

import cobol_compilers
import llm
import agent_stack
import parity_gate
from models import FileEvent, PhaseEvent
from planner import plan_repository
from work_items import (
    MAX_RETRY,
    MigrationPlan,
    WorkItem,
    WorkItemArtifact,
    assert_safe_rel,
    compose_ui_blocks,
    max_agent_slots,
    ready_concurrency,
    ready_items,
    sha256_file,
    transition,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "migration-state" / "runs"
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_dirs(run_id: str) -> tuple[Path, Path, Path]:
    root = RUNS_DIR / run_id
    return root / "source", root / "csharp", root / "workspaces"


async def persist_plan(conn: aiosqlite.Connection, plan: MigrationPlan) -> None:
    await conn.execute("DELETE FROM work_item_artifacts WHERE run_id = ?", (plan.run_id,))
    await conn.execute("DELETE FROM work_items WHERE run_id = ?", (plan.run_id,))
    await conn.execute("DELETE FROM migration_plans WHERE run_id = ?", (plan.run_id,))
    await conn.execute(
        "INSERT INTO migration_plans (plan_id, run_id, summary, solution_name, "
        "stage, ui_blocks_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (plan.plan_id, plan.run_id, plan.summary, plan.solution_name, plan.stage,
         json.dumps([b.to_dict() for b in plan.ui_blocks]), _now()),
    )
    for w in plan.work_items:
        await conn.execute(
            "INSERT INTO work_items (work_item_id, run_id, slug, title, kind, status, "
            "source_paths_json, expected_paths_json, depends_on_json, wave, retry_count, "
            "workspace_rel, agent_id, error, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
            # work_item_id is PRIMARY KEY with no run_id in the key. fallback_plan()
            # slugs are deterministic ("work-item-001", ...), so two runs of the same
            # repo collide on retry — namespace by run_id here only; `slug` (used for
            # filesystem paths) stays bare. Real defect found in run
            # 01M2KEE7PNRXRVTCVNSSH6XP3X: sqlite3.IntegrityError on retry.
            (f"{plan.run_id}:{w.work_item_id}", plan.run_id, w.slug, w.title, w.kind, w.status,
             json.dumps(w.source_paths), json.dumps(w.expected_paths),
             json.dumps(w.depends_on), w.wave, w.retry_count, w.workspace_rel,
             w.agent_id, w.error),
        )
    await conn.commit()


async def load_plan(conn: aiosqlite.Connection, run_id: str) -> MigrationPlan | None:
    cur = await conn.execute(
        "SELECT plan_id, summary, solution_name, stage, ui_blocks_json "
        "FROM migration_plans WHERE run_id = ?",
        (run_id,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    plan_id, summary, sln, stage, _ui_json = row
    cur = await conn.execute(
        "SELECT work_item_id, slug, title, kind, status, source_paths_json, "
        "expected_paths_json, depends_on_json, wave, retry_count, workspace_rel, "
        "agent_id, error FROM work_items WHERE run_id = ? ORDER BY wave, slug",
        (run_id,),
    )
    items: list[WorkItem] = []
    for r in await cur.fetchall():
        item = WorkItem(
            work_item_id=r[0], slug=r[1], title=r[2], kind=r[3], status=r[4],
            source_paths=json.loads(r[5] or "[]"),
            expected_paths=json.loads(r[6] or "[]"),
            depends_on=json.loads(r[7] or "[]"),
            wave=int(r[8] or 0), retry_count=int(r[9] or 0),
            workspace_rel=r[10] or "", agent_id=r[11], error=r[12],
        )
        acur = await conn.execute(
            "SELECT artifact_id, declared_path, sha256, integrated "
            "FROM work_item_artifacts WHERE work_item_id = ?",
            (item.work_item_id,),
        )
        item.artifacts = [
            WorkItemArtifact(a[0], item.work_item_id, a[1], a[2], bool(a[3]))
            for a in await acur.fetchall()
        ]
        items.append(item)
    plan = MigrationPlan(
        plan_id=plan_id, run_id=run_id, summary=summary, solution_name=sln,
        work_items=items, stage=stage or "pending",
    )
    csharp = RUNS_DIR / run_id / "csharp"
    downloadable = (csharp / "README.md").is_file()
    plan.ui_blocks = compose_ui_blocks(
        plan, live=False,
        build_ok=True if plan.stage in {"testing", "completed"} else None,
        test_ok=True if plan.stage == "completed" else None,
        downloadable=downloadable,
    )
    return plan


async def _set_item_status(conn: aiosqlite.Connection, run_id: str, item: WorkItem, nxt: str,
                           error: str | None = None) -> None:
    item.status = transition(item.status, nxt)  # type: ignore[assignment]
    item.error = error
    finished = _now() if nxt in {"completed", "failed"} else None
    started = _now() if nxt in {"analyzing", "generating", "building", "testing"} else None
    # Match by (run_id, slug), not item.work_item_id: a freshly-built plan (this
    # run's first pass) holds the bare slug in memory, but persist_plan() writes
    # "{run_id}:{slug}" as the DB primary key (namespacing fix for the PK
    # collision found 2026-09-15). Matching on the bare slug here silently
    # updated 0 rows all run — work_items stayed "pending" in the DB forever,
    # so a retry's load_plan() saw everything as not-done and reran from
    # scratch instead of resuming. slug + run_id was never touched by that fix
    # and is unique within a run by construction (fallback_plan/parse_planner
    # dedup), so it is the correct, always-consistent key here.
    await conn.execute(
        "UPDATE work_items SET status = ?, error = ?, agent_id = ?, "
        "retry_count = ?, started_at = COALESCE(started_at, ?), finished_at = ? "
        "WHERE run_id = ? AND slug = ?",
        (item.status, error, item.agent_id, item.retry_count, started, finished,
         run_id, item.slug),
    )
    await conn.commit()


async def _set_stage(conn: aiosqlite.Connection, plan: MigrationPlan, stage: str) -> None:
    plan.stage = stage
    await conn.execute(
        "UPDATE migration_plans SET stage = ? WHERE plan_id = ?",
        (stage, plan.plan_id),
    )
    await conn.commit()


# Real bug found 2026-09-16 (run 01M2NN5Q765RDGP4ZCV1Q6WC4H): two work items
# each legitimately declare their own `AccountRecord` type in their own
# `Application.UseCases.*` namespace, but the generated `Cli/Program.cs`
# referenced the bare simple name — CS0104 ambiguous reference, plus a
# CS0738 on any interface member typed with it. This burns a whole
# dotnet-build timeout/retry cycle discovering what a cheap static scan can
# catch instantly and hand straight to the "build" repair path, correctly
# labeled, before ever invoking dotnet.
_NAMESPACE_RE = re.compile(r"^\s*namespace\s+([\w.]+)", re.MULTILINE)
_TYPE_DECL_RE = re.compile(r"^\s*(?:public|internal)?\s*(?:sealed\s+|abstract\s+)?(?:class|record|struct)\s+(\w+)", re.MULTILINE)
_USING_RE = re.compile(r"^\s*using\s+([\w.]+)\s*;", re.MULTILINE)


def _strip_comments_and_strings(text: str) -> str:
    """Remove // line comments, /* */ block comments, and "..." string
    literals so a bare type-name match inside one of those can't produce a
    false positive. Deliberately crude (no verbatim/interpolated-string
    escaping) — good enough for a heuristic pre-build scan, real dotnet
    build is still the ground truth if this scan is wrong either way."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//.*", "", text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    return text


def _file_namespace_and_types(text: str) -> tuple[str, list[str]]:
    ns_match = _NAMESPACE_RE.search(text)
    namespace = ns_match.group(1) if ns_match else ""
    types = _TYPE_DECL_RE.findall(text)
    return namespace, types


def detect_type_name_collisions(csharp: Path) -> str:
    """Static pre-build scan: same simple type name declared in two
    different namespaces, both `using`d (unqualified) by the same file. Real,
    cheap check — no dotnet invocation. Returns a repair-ready diagnostic
    string, or "" if clean. Callers: orchestrator._verify_chain."""
    name_to_namespaces: dict[str, set[str]] = {}
    cs_files = [p for p in csharp.rglob("*.cs") if not any(part in {"obj", "bin"} for part in p.parts)]
    per_file: dict[Path, tuple[str, list[str], str]] = {}
    for path in cs_files:
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        namespace, types = _file_namespace_and_types(text)
        per_file[path] = (namespace, types, text)
        for t in types:
            name_to_namespaces.setdefault(t, set()).add(namespace)

    collisions = {name: nss for name, nss in name_to_namespaces.items() if len(nss) > 1}
    if not collisions:
        return ""

    problems: list[str] = []
    for path, (namespace, _types, text) in per_file.items():
        usings = set(_USING_RE.findall(text)) | {namespace}
        code_only = _strip_comments_and_strings(text)
        for name, nss in collisions.items():
            if len(nss & usings) < 2:
                continue
            # Two colliding namespaces both `using`d here — any reference to
            # `name` that is not the FULL root-qualified path is ambiguous.
            # A real bug found live: a PARTIAL qualifier like
            # "AccountLookup.AccountRecord" also fails to compile (CS0246 —
            # a using-imported namespace's own name is not itself a
            # resolvable segment) but has a "." right before the type name,
            # so a naive `(?<!\.)` lookbehind wrongly treated it as already
            # fixed. Only strip the exact full root-qualified forms; flag
            # anything else, bare or partially qualified.
            name_re = re.compile(rf"\b{re.escape(name)}\b")
            fully_qualified_forms = [f"{ns}.{name}" for ns in nss]
            stripped = code_only
            for fq in fully_qualified_forms:
                stripped = stripped.replace(fq, "")
            if name_re.search(stripped):
                problems.append(
                    f"{path.name}: '{name}' is ambiguous between "
                    + " and ".join(sorted(nss))
                    + " — every use must be fully qualified or aliased."
                )

    if not problems:
        return ""
    return (
        "Static pre-build check found ambiguous type references (would fail "
        "as CS0104/CS0738 in dotnet build):\n" + "\n".join(problems)
    )


def scaffold_solution(target: Path, sln: str) -> None:
    """Deterministic Clean Architecture skeleton — never LLM-generated.
    Real change 2026-09-15: layers moved from flat "{sln}.Layer/" folders
    (dotted names read poorly in a file tree — user: "odia esa jerarquia de
    puntos") to nested "src/Layer/", "tests/Layer.Tests/", with csproj
    filenames dropping the solution-name prefix too. C# namespaces are
    unaffected — they stay "{sln}.Application.UseCases.X" as a code-level
    identifier, independent of the filesystem layout."""
    target.mkdir(parents=True, exist_ok=True)
    src = target / "src"
    sdk = (
        '<Project Sdk="Microsoft.NET.Sdk">\n'
        "  <PropertyGroup>\n"
        "    <TargetFramework>net8.0</TargetFramework>\n"
        "    <ImplicitUsings>enable</ImplicitUsings>\n"
        "    <Nullable>enable</Nullable>\n"
        "  </PropertyGroup>\n"
        "</Project>\n"
    )
    exe = sdk.replace(
        "    <Nullable>enable</Nullable>\n",
        "    <Nullable>enable</Nullable>\n"
        "    <OutputType>Exe</OutputType>\n",
    )
    layers = {
        "Domain": sdk,
        "Application": sdk,
        "Infrastructure": sdk,
        "Cli": exe,
    }
    for name, xml in layers.items():
        d = src / name
        d.mkdir(parents=True, exist_ok=True)
        csproj = d / f"{name}.csproj"
        if not csproj.exists():
            extra = ""
            if name == "Application":
                extra = (
                    "  <ItemGroup>\n"
                    '    <ProjectReference Include="../Domain/Domain.csproj" />\n'
                    "  </ItemGroup>\n"
                )
            elif name == "Infrastructure":
                extra = (
                    "  <ItemGroup>\n"
                    '    <ProjectReference Include="../Application/Application.csproj" />\n'
                    "  </ItemGroup>\n"
                )
            elif name == "Cli":
                extra = (
                    "  <ItemGroup>\n"
                    '    <ProjectReference Include="../Application/Application.csproj" />\n'
                    '    <ProjectReference Include="../Infrastructure/Infrastructure.csproj" />\n'
                    "  </ItemGroup>\n"
                )
            csproj.write_text(xml.replace("</Project>", extra + "</Project>"))
    tests = target / "tests" / "Application.Tests"
    tests.mkdir(parents=True, exist_ok=True)
    tproj = tests / "Application.Tests.csproj"
    if not tproj.exists():
        tproj.write_text(
            '<Project Sdk="Microsoft.NET.Sdk">\n'
            "  <PropertyGroup>\n"
            "    <TargetFramework>net8.0</TargetFramework>\n"
            "    <ImplicitUsings>enable</ImplicitUsings>\n"
            "    <Nullable>enable</Nullable>\n"
            "    <IsPackable>false</IsPackable>\n"
            "  </PropertyGroup>\n"
            "  <ItemGroup>\n"
            '    <PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.11.1" />\n'
            '    <PackageReference Include="xunit" Version="2.9.2" />\n'
            '    <PackageReference Include="xunit.runner.visualstudio" Version="2.8.2" />\n'
            '    <PackageReference Include="Moq" Version="4.20.72" />\n'
            "  </ItemGroup>\n"
            "  <ItemGroup>\n"
            '    <ProjectReference Include="../../src/Application/Application.csproj" />\n'
            "  </ItemGroup>\n"
            "</Project>\n"
        )
    cli_program = src / "Cli" / "Program.cs"
    if not cli_program.exists():
        cli_program.write_text(
            "// Composition root — workers replace this file.\n"
            "Console.WriteLine(\"Cobalt CLI host\");\n"
        )


def prepare_workspace(run_id: str, item: WorkItem, source_dir: Path) -> Path:
    ws = RUNS_DIR / run_id / item.workspace_rel
    src = ws / "source"
    out = ws / "out"
    if src.exists():
        shutil.rmtree(src)
    src.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    for rel in item.source_paths:
        rel = assert_safe_rel(rel)
        origin = source_dir / rel
        if origin.is_file():
            dest = src / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, dest)
    return out


def integrate_workspace(item: WorkItem, out_dir: Path, dest_root: Path) -> list[WorkItemArtifact]:
    """Copy only declared expected_paths after hashing. Drop undeclared Markdown."""
    allowed = {assert_safe_rel(p) for p in item.expected_paths}
    artifacts: list[WorkItemArtifact] = []
    written = [
        p for p in out_dir.rglob("*")
        if p.is_file() and not any(part in {"obj", "bin"} for part in p.relative_to(out_dir).parts)
    ]
    for path in written:
        rel = str(path.relative_to(out_dir)).replace("\\", "/")
        if rel not in allowed:
            continue
        digest = sha256_file(path)
        target = dest_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if sha256_file(target) != digest:
            raise RuntimeError(f"hash mismatch integrating {rel}")
        artifacts.append(WorkItemArtifact(
            artifact_id=str(ULID()), work_item_id=item.work_item_id,
            declared_path=rel, sha256=digest, integrated=True,
        ))
    missing = allowed - {a.declared_path for a in artifacts}
    if missing:
        raise RuntimeError(f"{item.slug} missing declared files: {sorted(missing)}")
    item.artifacts = artifacts
    return artifacts


async def _store_artifacts(conn: aiosqlite.Connection, run_id: str,
                           artifacts: list[WorkItemArtifact]) -> None:
    for a in artifacts:
        await conn.execute(
            "INSERT INTO work_item_artifacts (artifact_id, work_item_id, run_id, "
            "declared_path, sha256, integrated) VALUES (?, ?, ?, ?, ?, 1)",
            (a.artifact_id, a.work_item_id, run_id, a.declared_path, a.sha256),
        )
    await conn.commit()


# COBALT-4 (audit 2026-09-16): migration-cost-governance exists as a skill
# document but nothing anywhere ever summed real spend and compared it to a
# limit — cost_logs was write-only. MAX_RETRY bounds ATTEMPT count, not
# dollars; a work item alone can push ~400K input tokens in one call. This
# is the actual enforcement point: a hard ceiling checked before every
# headless call a run makes, not just documentation of intent.
MAX_RUN_COST_USD = float(os.environ.get("COBALT_MAX_COST_USD", "10.00"))


async def _cumulative_cost(conn: aiosqlite.Connection, run_id: str) -> float:
    cur = await conn.execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM cost_logs WHERE run_id = ?", (run_id,),
    )
    row = await cur.fetchone()
    return float(row[0] or 0.0)


async def _cost_budget_exceeded(conn: aiosqlite.Connection, run_id: str) -> tuple[bool, float]:
    spent = await _cumulative_cost(conn, run_id)
    return spent >= MAX_RUN_COST_USD, spent


async def _log_cost(conn: aiosqlite.Connection, run_id: str, phase: str, meta: dict) -> None:
    await conn.execute(
        "INSERT INTO cost_logs (log_id, run_id, phase, agent_id, input_tokens, "
        "output_tokens, cost_usd, latency_ms, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(ULID()), run_id, phase, "claude-headless",
         int(meta.get("input_tokens") or 0), int(meta.get("output_tokens") or 0),
         float(meta.get("cost_usd") or 0), int(meta.get("latency_ms") or 0), _now()),
    )
    await conn.commit()


async def _dotnet(cmd: list[str], cwd: Path, timeout: int = 120) -> tuple[bool, str]:
    bin_ = cobol_compilers.find_dotnet()
    if not bin_:
        return False, "dotnet not found"
    env = cobol_compilers.dotnet_subprocess_env(bin_)
    proc = await asyncio.create_subprocess_exec(
        bin_, *cmd, cwd=str(cwd), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return False, "dotnet timed out"
    text = (stdout + stderr).decode(errors="replace")
    return proc.returncode == 0, text


def _emit(events: list, run_id: str, stage: str, item: WorkItem | None, status: str, detail: str) -> None:
    if item:
        events.append(FileEvent(
            run_id=run_id, phase=stage, file_path=item.slug, status=status, detail=detail,
        ))
        for path in item.expected_paths:
            events.append(FileEvent(
                run_id=run_id, phase=stage, file_path=path, status=status, detail=detail,
            ))
    else:
        events.append(PhaseEvent(phase=stage, skill="work-item-orchestrator", status=status, detail=detail))


async def ensure_plan(conn: aiosqlite.Connection, run_id: str, events: list) -> MigrationPlan:
    existing = await load_plan(conn, run_id)
    if existing and existing.work_items:
        # Same class of bug as the Documenting-phase fix: resuming an existing
        # plan (after a retry or a server restart mid-run) never re-emits the
        # Analyzing PhaseEvent, so a genuinely-already-done phase shows
        # "pending" forever in PhaseTimeline. Backfill it here.
        events.append(PhaseEvent(
            phase="Analyzing", skill="migration-planner", status="OK",
            detail=f"{existing.summary} — {len(existing.work_items)} work items (resumed)",
        ))
        return existing
    source_dir, _, _ = _run_dirs(run_id)
    events.append(PhaseEvent(
        phase="Analyzing", skill="migration-planner", status="RUNNING",
        detail="one planner session over a compact inventory",
    ))
    plan, cost = await plan_repository(run_id, source_dir)
    await persist_plan(conn, plan)
    await _log_cost(conn, run_id, "Analyzing", cost)
    events.append(PhaseEvent(
        phase="Analyzing", skill="migration-planner", status="OK",
        detail=f"{plan.summary} — {len(plan.work_items)} work items ({cost.get('source')})",
    ))
    return plan


async def _run_worker(conn: aiosqlite.Connection, run_id: str, plan: MigrationPlan,
                      item: WorkItem, source_dir: Path, csharp: Path, events: list) -> None:
    item.agent_id = f"agent-{item.slug}"
    await _set_item_status(conn, run_id, item, "generating")
    _emit(events, run_id, "Generating", item, "RUNNING", f"{item.title} in {item.workspace_rel}")
    out = prepare_workspace(run_id, item, source_dir)
    sources = {}
    for rel in item.source_paths:
        p = source_dir / rel
        if p.is_file():
            sources[rel] = p.read_text(errors="replace")
    # Real defect found 2026-09-15 (run 01M2KN4KKM3XDPQ87S7XJHPNKH): a "cli"
    # work item had zero visibility into the actual namespaces/class names its
    # dependencies produced, so the LLM hallucinated plausible-looking ones
    # ("UseCases.AccountLookup" from a different run's naming) that don't
    # exist here — 9 CS0234/CS0246 errors, 2 repair attempts both exhausted.
    # Feed it the real generated code for anything it depends on.
    if item.depends_on and item.kind in {"cli", "persistence", "tests"}:
        # Real defect found 2026-09-15 (run 01M2KQJVYKX7JY1E0WEQ3REMT0): feeding
        # the FULL text of every already-generated .cs file ballooned the
        # prompt to ~400K input tokens (vs ~150K normal) and the CLI work item
        # failed twice with no real diagnostic (exit=1, empty stderr) — almost
        # certainly the model choking on volume, not a genuine compile need.
        # A compact API-surface summary (namespace + public type declarations
        # only, no method bodies) gives the same real-names ground truth at a
        # fraction of the size.
        #
        # Real defect found 2026-09-15 (run 01M2M7VBYJ557FM603RWR5BRF7): the
        # original version of this regex only captured namespace/type
        # DECLARATION lines, never a method's own signature or a constructor —
        # so a "cli"/"tests" item could see that `AccountLookupHandler` exists
        # but never its real method name, and guessed one (`Handle()` instead
        # of the real `Execute(long)`) — a real CS1061 build failure. A
        # SEPARATE run (01M2M036AND64G9YQ8WT59TMAB) hit the same class of bug
        # in a generated test: it invented `IAccountRepository`/`Account` types
        # wholesale instead of using the real `IAccountManagementPort`/
        # `AccountRecord`. Extended to also capture constructors, public
        # method signatures, and interface member declarations — verified
        # against every real generated file in a live run: correctly pulled
        # `Execute(long accountNumber)`, `AccountLookupHandler(IAccountLookupPort
        # port)`, and every interface member, with only one harmless
        # false-positive (a `return SomeMethod(...)` call line, not a
        # declaration — noise, not a wrong fact).
        sig_re = re.compile(
            r"^\s*("
            r"namespace\s+[\w.]+"
            r"|public\s+(?:sealed\s+|abstract\s+)?(?:class|interface|record|enum)\s+\w+.*"
            r"|public\s+(?:async\s+|static\s+)*[\w<>,?\[\]\.]+\s+\w+\s*\([^;{]*\)"
            r"|public\s+[A-Z]\w*\s*\([^;{]*\)"
            r"|[\w<>,?\[\]\.]+\s+\w+\s*\([^;{]*\)\s*;"
            r")\s*$", re.MULTILINE,
        )
        for rel in sorted(csharp.rglob("*.cs")):
            if any(part in {"bin", "obj"} for part in rel.parts):
                continue
            text = rel.read_text(errors="replace")
            sigs = sig_re.findall(text)
            if sigs:
                sources[f"(already generated, signatures only) {rel.relative_to(csharp)}"] = "\n".join(sigs)
    try:
        res = await llm.convert_work_item(
            sources, item.expected_paths, out, plan.solution_name, item.title, item.kind,
            agent_circumstance=agent_stack.circumstance_for_run(run_id),
            on_progress=lambda msg: events.append(FileEvent(
                run_id=run_id, phase="Generating", file_path=item.slug,
                status="RUNNING", detail=msg,
            )),
        )
        await _log_cost(conn, run_id, "Generating", {
            "cost_usd": res.cost_usd, "input_tokens": res.input_tokens,
            "output_tokens": res.output_tokens, "latency_ms": res.latency_ms,
        })
        arts = integrate_workspace(item, out, csharp)
        await _store_artifacts(conn, run_id, arts)
        await _set_item_status(conn, run_id, item, "completed")
        _emit(events, run_id, "Generating", item, "OK", f"{len(arts)} files integrated")
    except Exception as exc:
        # COBALT-7 (audit 2026-09-16): HeadlessInvocationError carries real
        # cost_usd/token counts for tokens already spent before the crash —
        # this branch used to drop that spend entirely, so a run's real cost
        # (via cost_logs) undercounted every failed attempt, not just
        # successful ones.
        if isinstance(exc, llm.HeadlessInvocationError):
            await _log_cost(conn, run_id, "Generating", {
                "cost_usd": exc.cost_usd, "input_tokens": exc.input_tokens,
                "output_tokens": exc.output_tokens, "latency_ms": exc.latency_ms,
            })
        item.retry_count += 1
        await _set_item_status(conn, run_id, item, "failed", str(exc)[:400])
        _emit(events, run_id, "Generating", item, "FAILED", str(exc)[:400])


async def execute_migration(run_id: str, conn: aiosqlite.Connection, events: list) -> None:
    source_dir, csharp, _ws = _run_dirs(run_id)

    # 2026-09-16 (user, verbatim: "si queremos lo verdaderamente agentico debe
    # instalarse lo necesario supervisiondo"): first stage, before Planning —
    # confirm/install the toolchain the ORIGINAL COBOL and TARGET C# build
    # actually need, in this already-isolated run environment. Every install
    # command's real output is logged as a PhaseEvent (supervised, visible
    # live in the UI), never silent.
    events.append(PhaseEvent(
        phase="Environment Setup", skill="toolchain-check", status="RUNNING",
        detail="checking cobc (GnuCOBOL) and dotnet",
    ))

    def _on_step(label: str, result: dict) -> None:
        events.append(PhaseEvent(
            phase="Environment Setup", skill="toolchain-check", status="RUNNING",
            detail=f"{label}: exit={result['exit_code']}\n{result['stdout'][:500]}",
        ))

    toolchain_ready = cobol_compilers.ensure_toolchain(_on_step)
    events.append(PhaseEvent(
        phase="Environment Setup", skill="toolchain-check",
        status="OK" if toolchain_ready else "BLOCKED",
        detail="cobc + dotnet ready" if toolchain_ready
        else "toolchain install failed — see steps above",
    ))
    if not toolchain_ready:
        await conn.execute(
            "UPDATE migration_runs SET status = 'FAILED', finished_at = ? WHERE run_id = ?",
            (datetime.now(timezone.utc).isoformat(), run_id),
        )
        await conn.commit()
        events.append(PhaseEvent(phase="__done__", skill="pipeline", status="OK", detail="stream complete"))
        return

    plan = await ensure_plan(conn, run_id, events)
    # Real defect found 2026-09-15 (run 01M2KM41FKP2V5Y38628VCWYRC): if the
    # process dies mid-item (a server restart, a crash) while a work item is
    # "generating", that item is orphaned forever — ready_items() only revives
    # "pending" items, so the loop below finds nothing left to do and the
    # pipeline sails on to Build/Test/Docs missing that item's file entirely,
    # reporting a false PASSED. A fresh process can never have a live task for
    # an item still marked as an in-progress transient state, so treat any
    # such item as interrupted and make it eligible to run again.
    for item in plan.work_items:
        if item.status in {"generating", "analyzing", "building", "testing"}:
            await _set_item_status(conn, run_id, item, "pending",
                                    error=f"resumed after interrupted {item.status}")
    # User, 2026-09-15 (run 01M2KY35EWPMXSCY5JWP2BVKV5): a retry of a FAILED run
    # must resume "desde donde quedo" (from where it stopped), not restart from
    # zero — but it must also not leave permanently-exhausted items stuck
    # "failed" forever. ready_items() only ever returns "pending" items, and
    # nothing above revives "failed" ones, so a manual retry (POST /start) sailed
    # past those 3 stuck items untouched instead of trying them again. Reset
    # retry_count to 0 here: a user-triggered retry is a new attempt cycle, not
    # a continuation of the exhausted one that already hit MAX_RETRY.
    for item in plan.work_items:
        if item.status == "failed":
            item.retry_count = 0
            await _set_item_status(conn, run_id, item, "pending",
                                    error="resumed after failed (manual retry)")
    # start_pipeline() resets the in-memory events list to [] on every retry
    # (SSE/detail history is not durably persisted for this orchestrator, unlike
    # the old 9-phase pipeline's run_events snapshot). Work items already
    # "completed" from an earlier attempt are correctly skipped by ready_items()
    # below and never re-run — but that also means this pass emits zero events
    # for them, so a genuinely PASSED retry could show e.g. "11 of 15" with the
    # already-done Cli/Persistence items invisible. Backfill one synthetic OK
    # event per already-completed item so this run's event log always reflects
    # its full real state, not just what happened in the current process.
    for item in plan.work_items:
        if item.status == "completed":
            _emit(events, run_id, "Generating", item, "OK",
                  f"{len(item.expected_paths)} files integrated (earlier attempt)")
    await _set_stage(conn, plan, "generating")
    scaffold_solution(csharp, plan.solution_name)
    events.append(PhaseEvent(
        phase="Generating", skill="work-item-orchestrator", status="RUNNING",
        detail=f"scaffold {plan.solution_name}; max {max_agent_slots()} agents",
    ))

    pending_docs = [w for w in plan.work_items if w.kind == "documentation"]

    while True:
        ready = [w for w in ready_items(plan) if w.kind != "documentation"]
        if not ready:
            break
        slots = ready_concurrency(len(ready))
        batch = ready[:slots]
        await asyncio.gather(*[
            _run_worker(conn, run_id, plan, item, source_dir, csharp, events)
            for item in batch
        ])
        failed = [w for w in batch if w.status == "failed" and w.retry_count < MAX_RETRY]
        for w in failed:
            w.status = "pending"  # type: ignore[assignment]
            await conn.execute(
                "UPDATE work_items SET status = 'pending', error = NULL WHERE work_item_id = ?",
                (w.work_item_id,),
            )
            await conn.commit()
        if any(w.status == "failed" and w.retry_count >= MAX_RETRY for w in plan.work_items
               if w.kind != "documentation"):
            await _set_stage(conn, plan, "failed")
            events.append(PhaseEvent(
                phase="Generating", skill="work-item-orchestrator", status="BLOCKED",
                detail="work item failed after retries — not advancing to tests",
            ))
            events.append(PhaseEvent(phase="__done__", skill="pipeline", status="OK", detail="stream complete"))
            return

    # 2026-09-15 (user, verbatim: "odio que... solo diga ya failed... en lugar
    # de solo haber hecho una debugeada"; "en prod debe corregirse por si
    # mismo, sin intervencion"): Building, Testing and Parity Validation used
    # to be three separate gates where only Building auto-repaired on failure
    # — a test-compile error or a real COBOL-vs-C# behavior mismatch stopped
    # the whole run cold and needed a human to hand-diagnose and hand-patch
    # the generated C#. Real cases hit this session: a byte-offset bug in a
    # persistence adapter (crash), a missing "+" sign in console formatting
    # (cosmetic mismatch), an inconsistent COBOL record layout across two
    # programs sharing one file, and a hallucinated test API. A single unified
    # verify-then-repair loop now covers all three gates: any failure anywhere
    # in Build/Test/Parity gets a real repair attempt (fed the ACTUAL failure
    # content — compile error, test output, or COBOL-vs-C# diff), then the
    # whole chain re-verifies from Build forward, up to MAX_RETRY times.
    cli_dir = csharp / "src" / "Cli"

    async def _verify_chain() -> tuple[bool, str, str]:
        """Runs Build -> Test -> Parity, stopping at the first failure.
        Returns (all_ok, failed_stage, log) — failed_stage is "" when all_ok."""
        await _set_stage(conn, plan, "building")
        events.append(PhaseEvent(
            phase="Building", skill="dotnet-build", status="RUNNING", detail="dotnet build gate",
        ))
        collision_diag = detect_type_name_collisions(csharp)
        if collision_diag:
            events.append(PhaseEvent(
                phase="Building", skill="dotnet-build", status="BLOCKED",
                detail=collision_diag[:600],
            ))
            # Own stage key ("type_collision", not "build") — a heuristic
            # regex scan is not real dotnet, so its own failure must not
            # spend the same MAX_RETRY budget a genuine dotnet build error
            # gets (Codex audit finding 2026-09-16): a stubborn false
            # positive here would otherwise exhaust "build"'s budget before
            # a single real `dotnet build` ever ran.
            return False, "type_collision", collision_diag
        ok, log = await _dotnet(["build"], cli_dir if cli_dir.is_dir() else csharp)
        events.append(PhaseEvent(
            phase="Building", skill="dotnet-build",
            status="OK" if ok else "BLOCKED",
            detail="build succeeded" if ok else (log[:600] or "build failed"),
        ))
        if not ok:
            return False, "build", log

        await _set_stage(conn, plan, "testing")
        test_csproj = next((p for p in csharp.rglob("*Tests.csproj")), None)
        if test_csproj:
            events.append(PhaseEvent(
                phase="Testing", skill="dotnet-test", status="RUNNING", detail="dotnet test gate",
            ))
            test_ok, test_log = await _dotnet(["test", str(test_csproj)], csharp, timeout=180)
            # Real defect found 2026-09-15 (run 01M2KPAMSM89P30VCHGFD7C9MY):
            # `dotnet test` exits 0 (success) when the test project compiles
            # but contains ZERO [Fact]/[Theory] methods — "No test is
            # available in ...dll" is a warning, not a failure, to the exit
            # code. Treat that string as a real failure, not a pass.
            if test_ok and "No test is available" in test_log:
                test_ok = False
            events.append(PhaseEvent(
                phase="Testing", skill="dotnet-test",
                status="OK" if test_ok else "BLOCKED",
                detail=("tests passed" if test_ok else test_log[:600]),
            ))
            if not test_ok:
                return False, "test", test_log

        # Real Phase 6 gate, wired 2026-09-15: compiles each real COBOL
        # program as an oracle, runs the generated C# candidate against the
        # same derived fixture, byte-diffs stdout(+mutated file for
        # file_batch programs), and writes one parity_verdicts row per
        # program. Previously the pipeline certified PASSED from dotnet
        # build/test alone — never once compared COBOL-vs-C# behavior on the
        # same input (design/14 Gap 2).
        events.append(PhaseEvent(
            phase="Parity Validation", skill="parity-validation", status="RUNNING",
            detail="compiling COBOL oracle(s) + running C# candidate per program",
        ))
        parity_ok, parity_detail = await parity_gate.run_parity_gate(
            conn, run_id, plan, source_dir, csharp, events,
        )
        events.append(PhaseEvent(
            phase="Parity Validation", skill="parity-validation",
            status="OK" if parity_ok else "BLOCKED",
            detail=parity_detail[:600],
        ))
        if not parity_ok:
            return False, "parity", parity_detail
        return True, "", ""

    _REPAIR_FNS = {
        "build": (llm.repair_csharp, "compiling"),
        "type_collision": (llm.repair_type_collision, "ambiguous type name"),
        "test": (llm.repair_test_failure, "test failure"),
        "parity": (llm.repair_parity_mismatch, "COBOL-vs-C# mismatch"),
    }

    # Real defect found 2026-09-15 (run 01M2M036AND64G9YQ8WT59TMAB, user: "sin
    # que tu estes corrigiendo manualmente... se ejecutara con exito"): a single
    # repair_attempts counter shared across Build/Test/Parity meant a run that
    # hit three DIFFERENT real bugs (a transient build timeout, a hallucinated
    # test namespace, and a real parity byte-offset crash) burned its whole
    # MAX_RETRY budget on the first two — genuinely auto-fixed both — and then
    # had zero attempts left for the third, unrelated bug. Each gate gets its
    # own independent budget instead, so one gate's flakiness never starves
    # another gate's real, fixable bug.
    stage_attempts: dict[str, int] = {"build": 0, "type_collision": 0, "test": 0, "parity": 0}
    ok, failed_stage, log = await _verify_chain()
    while not ok and stage_attempts[failed_stage] < MAX_RETRY:
        over_budget, spent = await _cost_budget_exceeded(conn, run_id)
        if over_budget:
            events.append(PhaseEvent(
                phase="Repairing", skill="bugfix-loop", status="BLOCKED",
                detail=f"cost cap reached (${spent:.2f} >= ${MAX_RUN_COST_USD:.2f}) — stopping repair attempts",
            ))
            break
        stage_attempts[failed_stage] += 1
        repair_attempts = stage_attempts[failed_stage]
        repair_fn, label = _REPAIR_FNS[failed_stage]
        events.append(PhaseEvent(
            phase="Repairing", skill="bugfix-loop", status="RUNNING",
            detail=f"repair attempt {repair_attempts}/{MAX_RETRY} ({label})",
        ))
        try:
            res = await repair_fn(csharp, log)
            await _log_cost(conn, run_id, "Repairing", {
                "cost_usd": res.cost_usd, "input_tokens": res.input_tokens,
                "output_tokens": res.output_tokens, "latency_ms": res.latency_ms,
            })
        except llm.HeadlessInvocationError as exc:
            # Real defect found 2026-09-15 (run 01M2M036AND64G9YQ8WT59TMAB, user:
            # "odia que solo diga FAILED en vez de haber hecho una debugeada"): the
            # headless repair agent can Write a correct fix to disk and then still
            # crash before returning its JSON result envelope (network hiccup,
            # transient CLI error) — raising HeadlessInvocationError here. Giving
            # up immediately treated a transient reporting failure as if the fix
            # itself had failed; verified on a real run that the build passed
            # cleanly right after such a crash. Always re-verify before deciding
            # this attempt was wasted.
            events.append(PhaseEvent(
                phase="Repairing", skill="bugfix-loop", status="RUNNING",
                detail=f"repair agent errored ({str(exc)[:200]}) — re-verifying anyway",
            ))
            # COBALT-7: this crash still spent real tokens before failing —
            # log them instead of dropping that cost from cost_logs.
            await _log_cost(conn, run_id, "Repairing", {
                "cost_usd": exc.cost_usd, "input_tokens": exc.input_tokens,
                "output_tokens": exc.output_tokens, "latency_ms": exc.latency_ms,
            })
        ok, failed_stage, log = await _verify_chain()
        if ok:
            events.append(PhaseEvent(
                phase="Repairing", skill="bugfix-loop", status="OK",
                detail=f"repaired on attempt {repair_attempts}",
            ))
    if not ok:
        await _set_stage(conn, plan, "failed")
        events.append(PhaseEvent(phase="__done__", skill="pipeline", status="OK", detail="stream complete"))
        return

    # Real defect found 2026-09-15: this loop only emitted FileEvents for the
    # documentation work item, never a PhaseEvent — so PhaseTimeline (which
    # tracks phases, not files) showed "Documenting: pending" forever even on
    # a genuinely PASSED run that had already written README.md/MIGRATION.md.
    if any(w.status == "pending" for w in pending_docs):
        events.append(PhaseEvent(
            phase="Documenting", skill="migration-docs", status="RUNNING",
            detail="writing README.md + MIGRATION.md",
        ))
    for item in pending_docs:
        if item.status != "pending":
            continue
        item.agent_id = f"agent-{item.slug}"
        await _set_item_status(conn, run_id, item, "generating")
        try:
            res = await llm.write_mvp_docs(csharp)
            await _log_cost(conn, run_id, "Documenting", {
                "cost_usd": res.cost_usd, "input_tokens": res.input_tokens,
                "output_tokens": res.output_tokens, "latency_ms": res.latency_ms,
            })
            for rel in item.expected_paths:
                p = csharp / rel
                if p.is_file():
                    art = WorkItemArtifact(
                        artifact_id=str(ULID()), work_item_id=item.work_item_id,
                        declared_path=rel, sha256=sha256_file(p), integrated=True,
                    )
                    item.artifacts.append(art)
                    await _store_artifacts(conn, run_id, [art])
            await _set_item_status(conn, run_id, item, "completed")
            _emit(events, run_id, "Documenting", item, "OK", "README.md + MIGRATION.md")
        except Exception as exc:
            await _set_item_status(conn, run_id, item, "failed", str(exc)[:400])
            _emit(events, run_id, "Documenting", item, "FAILED", str(exc)[:400])

    if pending_docs and all(w.status == "completed" for w in pending_docs):
        events.append(PhaseEvent(
            phase="Documenting", skill="migration-docs", status="OK",
            detail="README.md + MIGRATION.md",
        ))

    if any(w.status == "failed" for w in pending_docs):
        await _set_stage(conn, plan, "failed")
        events.append(PhaseEvent(
            phase="Documenting", skill="migration-docs", status="BLOCKED",
            detail="README.md / MIGRATION.md were not written",
        ))
        events.append(PhaseEvent(phase="__done__", skill="pipeline", status="OK", detail="stream complete"))
        return

    await _set_stage(conn, plan, "completed")
    events.append(PhaseEvent(
        phase="Generating", skill="work-item-orchestrator", status="OK",
        detail=f"manifest complete — {len(plan.work_items)} units",
    ))
    events.append(PhaseEvent(phase="__done__", skill="pipeline", status="OK", detail="stream complete"))
