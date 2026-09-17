"""Exploration Subsystem API — isolated from migration orchestrator."""
from __future__ import annotations

import asyncio
import json
import shutil
import traceback
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
import aiosqlite
from ulid import ULID

import exploration_core as core
import exploration_orchestrator
from db import get_db, open_db
from models import ExplorationSessionResponse, PhaseEvent

from routers import pipeline as pipeline_router

router = APIRouter(prefix="/migration", tags=["exploration"])

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = REPO_ROOT / "migration-state" / "runs"
_exploration_tasks: dict[str, asyncio.Task] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _ensure_session(conn: aiosqlite.Connection, run_id: str) -> None:
    cur = await conn.execute(
        "SELECT 1 FROM exploration_sessions WHERE run_id = ?", (run_id,),
    )
    if await cur.fetchone():
        return
    await conn.execute(
        "INSERT INTO exploration_sessions (run_id, status, started_at, finished_at, "
        "draft_pack_json, locked_pack_json, locked_at) VALUES (?, ?, NULL, NULL, NULL, NULL, NULL)",
        (run_id, "DRAFT"),
    )
    await conn.commit()



def _documentation_root(run_id: str) -> Path:
    return RUNS_DIR / run_id / "docs-cobol-accounting-system" / "docs"


def _documentation_paths_on_disk(run_id: str) -> list[str]:
    root = _documentation_root(run_id)
    if not root.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())


def _hydrate_pack_documentation(run_id: str, pack: dict | None) -> dict | None:
    """Runs saved before documentation metadata was persisted may still have files on disk."""
    if not pack:
        return pack
    merged = dict(pack)
    paths = _documentation_paths_on_disk(run_id)
    if paths:
        doc = dict(pack.get("documentation") or {})
        existing = doc.get("documents") or []
        if not existing or len(existing) < len(paths):
            doc["documents"] = paths
        doc.setdefault("scope", "Complete repository AS-IS exploration only; no TO-BE or migration artifacts")
        doc.setdefault("root", str(_documentation_root(run_id)))
        doc.setdefault("agent_status", doc.get("agent_status") or "hydrated from disk")
        graph_path = _documentation_root(run_id) / "documentation_graph.json"
        if graph_path.is_file() and not doc.get("graph"):
            try:
                doc["graph"] = json.loads(graph_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        merged["documentation"] = doc
    graph_file = RUNS_DIR / run_id / "exploration" / "estate_relation_graph.json"
    if graph_file.is_file():
        try:
            loaded = json.loads(graph_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and loaded.get("generated_by") == "agent" and loaded.get("nodes"):
                merged["relation_graph"] = loaded
        except json.JSONDecodeError:
            pass
    source_root = RUNS_DIR / run_id / "source"
    for prog in merged.get("programs") or []:
        rel = prog.get("path") or ""
        fp = source_root / rel
        if not fp.is_file():
            continue
        nodes, edges = core.procedure_flowchart(fp.read_text(errors="replace"), prog.get("program_id"))
        nodes, edges = core.compress_flowchart(nodes, edges)
        prog["flow_nodes"] = nodes
        prog["flow_edges"] = edges
    existing = merged.get("relation_graph") or {}
    if existing.get("generated_by") != "agent":
        merged["relation_graph"] = core.estate_logic_flowchart(merged.get("programs") or [])
        graph_file.parent.mkdir(parents=True, exist_ok=True)
        graph_file.write_text(json.dumps(merged["relation_graph"], indent=2), encoding="utf-8")
    return merged


async def _load_session(conn: aiosqlite.Connection, run_id: str) -> dict | None:
    cur = await conn.execute(
        "SELECT status, started_at, finished_at, draft_pack_json, locked_pack_json, locked_at "
        "FROM exploration_sessions WHERE run_id = ?",
        (run_id,),
    )
    row = await cur.fetchone()
    if not row:
        return None
    draft = json.loads(row[3]) if row[3] else None
    locked = json.loads(row[4]) if row[4] else None
    draft = _hydrate_pack_documentation(run_id, draft)
    locked = _hydrate_pack_documentation(run_id, locked)
    return {
        "run_id": run_id,
        "status": row[0],
        "started_at": row[1],
        "finished_at": row[2],
        "draft_pack": draft,
        "locked_pack": locked,
        "locked_at": row[5],
        "live": _exploration_is_live(run_id),
    }


def _exploration_is_live(run_id: str) -> bool:
    t = _exploration_tasks.get(run_id)
    return t is not None and not t.done()


async def _execute_exploration(run_id: str) -> None:
    conn = await open_db()
    snapshot_conn = await open_db()
    snapshot_task = asyncio.create_task(pipeline_router._snapshot_events_loop(run_id, snapshot_conn))
    events = pipeline_router._run_state.setdefault(run_id, [])
    try:
        await exploration_orchestrator.execute_exploration(run_id, conn, events)
    except Exception:
        tb = traceback.format_exc()
        print(f"[_execute_exploration] run_id={run_id} crashed:\n{tb}", flush=True)
        events.append(PhaseEvent(
            phase="Exploration · Modules", skill="exploration", status="BLOCKED",
            detail=tb.strip().splitlines()[-1] if tb.strip() else "exploration failed",
        ))
        # Real bug found live 2026-09-16 (two concurrent Exploration runs
        # hit "database is locked" on a genuine write collision): this
        # cleanup write used the SAME conn that just failed, with no
        # try/except of its own — if the lock was still held, THIS write
        # also raised, unhandled, leaving status='RUNNING' forever (a
        # permanently stuck run with no live task — "Task exception was
        # never retrieved" in the log). A fresh connection + its own
        # try/except means a crash always leaves a terminal, honest status.
        try:
            cleanup_conn = await open_db()
            try:
                await cleanup_conn.execute(
                    "UPDATE exploration_sessions SET status = ?, finished_at = ? WHERE run_id = ?",
                    ("FAILED", _now(), run_id),
                )
                await cleanup_conn.commit()
            finally:
                await cleanup_conn.close()
        except Exception as cleanup_exc:
            print(f"[_execute_exploration] run_id={run_id} FAILED-status write also failed: {cleanup_exc}", flush=True)
    finally:
        snapshot_task.cancel()
        try:
            await snapshot_task
        except asyncio.CancelledError:
            pass
        await snapshot_conn.close()
        await conn.close()
        events.append(PhaseEvent(
            phase=pipeline_router._DONE_PHASE, skill="exploration", status="OK", detail="exploration stream end",
        ))


@router.get("/{run_id}/exploration/status", response_model=ExplorationSessionResponse)
async def exploration_status(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    cur = await conn.execute("SELECT 1 FROM migration_runs WHERE run_id = ?", (run_id,))
    if not await cur.fetchone():
        raise HTTPException(404, f"No run found for run_id={run_id}")
    await _ensure_session(conn, run_id)
    data = await _load_session(conn, run_id)
    assert data
    return ExplorationSessionResponse(**data)


@router.get("/{run_id}/exploration/pack")
async def exploration_pack(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    data = await _load_session(conn, run_id)
    if not data:
        raise HTTPException(404, "No exploration session")
    pack = data["locked_pack"] or data["draft_pack"]
    if not pack:
        raise HTTPException(404, "No exploration pack yet — run exploration first")
    return pack


def _documentation_file(run_id: str, relative_path: str) -> Path:
    root = _documentation_root(run_id).resolve()
    candidate = (root / relative_path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise HTTPException(404, "Documentation file not found")
    return candidate



@router.get("/{run_id}/exploration/docs/manifest")
async def exploration_docs_manifest(run_id: str):
    """List AS-IS deliverables from disk (source of truth for the UI tree)."""
    paths = _documentation_paths_on_disk(run_id)
    if not paths:
        raise HTTPException(404, "No exploration documentation on disk for this run")
    root = _documentation_root(run_id)
    corpus_manifest = root.parent / "analysis-corpus" / "CORPUS-MANIFEST.json"
    corpus = None
    if corpus_manifest.is_file():
        try:
            raw = json.loads(corpus_manifest.read_text(encoding="utf-8"))
            corpus = {
                "files_copied": int(raw.get("files_copied") or 0),
                "archive_members_expanded": int(raw.get("archive_members_expanded") or 0),
            }
        except (json.JSONDecodeError, TypeError, ValueError):
            corpus = None
    agent_status = "on disk"
    graph = None
    graph_path = root / "documentation_graph.json"
    if graph_path.is_file():
        try:
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            graph = None
    return {
        "run_id": run_id,
        "documents": paths,
        "agent_status": agent_status,
        "corpus": corpus,
        "graph": graph,
    }

@router.get("/{run_id}/exploration/docs.zip")
async def exploration_docs_zip(run_id: str):
    root = _documentation_root(run_id)
    if not root.is_dir():
        raise HTTPException(404, "No exploration documentation yet")
    archive_base = RUNS_DIR / run_id / "exploration-documentation"
    archive = Path(shutil.make_archive(str(archive_base), "zip", root_dir=root.parent, base_dir=root.name))
    return FileResponse(archive, media_type="application/zip", filename="cobol-as-is-documentation.zip")


@router.get("/{run_id}/exploration/docs/{relative_path:path}")
async def exploration_document_file(run_id: str, relative_path: str):
    target = _documentation_file(run_id, relative_path)
    return FileResponse(target, filename=target.name)


@router.post("/{run_id}/exploration/start", response_model=ExplorationSessionResponse)
async def exploration_start(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    cur = await conn.execute("SELECT 1 FROM migration_runs WHERE run_id = ?", (run_id,))
    if not await cur.fetchone():
        raise HTTPException(404, f"No run found for run_id={run_id}")
    if not (RUNS_DIR / run_id / "source").is_dir():
        raise HTTPException(400, "Intake source missing")
    if _exploration_is_live(run_id):
        data = await _load_session(conn, run_id)
        return ExplorationSessionResponse(**data)
    await _ensure_session(conn, run_id)
    cur = await conn.execute(
        "SELECT status FROM exploration_sessions WHERE run_id = ?", (run_id,),
    )
    row = await cur.fetchone()
    if row and row[0] == "LOCKED":
        raise HTTPException(409, "Exploration is locked — unlock not supported in this build")
    if not pipeline_router._run_is_live(run_id):
        pipeline_router._run_state[run_id] = []
    task = asyncio.create_task(_execute_exploration(run_id))
    _exploration_tasks[run_id] = task

    def _done(_t: asyncio.Task) -> None:
        _exploration_tasks.pop(run_id, None)

    task.add_done_callback(_done)
    data = await _load_session(conn, run_id)
    return ExplorationSessionResponse(**data)


@router.post("/{run_id}/exploration/lock", response_model=ExplorationSessionResponse)
async def exploration_lock(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    if _exploration_is_live(run_id):
        raise HTTPException(409, "Wait for exploration to finish before locking")
    source_dir = RUNS_DIR / run_id / "source"
    if not source_dir.is_dir():
        raise HTTPException(400, "Intake source missing")
    data = await _load_session(conn, run_id)
    if not data or not data.get("draft_pack"):
        raise HTTPException(400, "No draft pack — run exploration first")
    # Real bug found 2026-09-16 (Codex audit via docs-package-architect agent):
    # this used to call core.build_exploration_pack(..., locked=True) here,
    # which re-derives the pack FROM SCRATCH — silently discarding the real
    # agent-produced business rules (_agentic_business_rules) and any human
    # module notes (POST .../notes) already sitting in draft_pack, replacing
    # them with fresh deterministic_draft stubs. Promote the EXISTING draft
    # pack instead — locking must never regress already-improved data.
    now = _now()
    pack = dict(data["draft_pack"])
    pack["locked_at"] = now
    await conn.execute(
        "UPDATE exploration_sessions SET locked_pack_json = ?, locked_at = ?, status = ?, "
        "draft_pack_json = ? WHERE run_id = ?",
        (json.dumps(pack), now, "LOCKED", json.dumps(pack), run_id),
    )
    await conn.commit()
    data = await _load_session(conn, run_id)
    return ExplorationSessionResponse(**data)


@router.post("/{run_id}/exploration/modules/{module_id}/notes")
async def exploration_module_notes(
    run_id: str, module_id: str, body: dict, conn: aiosqlite.Connection = Depends(get_db),
):
    text = (body.get("text") or "").strip()
    data = await _load_session(conn, run_id)
    if not data or not data.get("draft_pack"):
        raise HTTPException(404, "No draft pack")
    pack = data["draft_pack"]
    found = False
    for mod in pack.get("modules", []):
        if mod.get("module_id") == module_id:
            mod["human_notes"] = text
            found = True
            break
    if not found:
        raise HTTPException(404, f"Unknown module {module_id}")
    await conn.execute(
        "UPDATE exploration_sessions SET draft_pack_json = ? WHERE run_id = ?",
        (json.dumps(pack), run_id),
    )
    await conn.commit()
    return {"module_id": module_id, "human_notes": text}
