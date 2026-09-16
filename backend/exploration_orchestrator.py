"""Exploration Subsystem foreman — parallel per-file structural work."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ulid import ULID

import exploration_core as core
from models import FileEvent, PhaseEvent
from work_items import inventory_source

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "migration-state" / "runs"
MAX_STRUCTURAL_PARALLEL = int(os.environ.get("COBALT_EXPLORATION_PARALLEL", "8"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _set_session(conn, run_id: str, status: str, **extra: str) -> None:
    cols = ["status = ?"]
    vals: list = [status]
    for k, v in extra.items():
        cols.append(f"{k} = ?")
        vals.append(v)
    vals.append(run_id)
    await conn.execute(
        f"UPDATE exploration_sessions SET {', '.join(cols)} WHERE run_id = ?",
        vals,
    )
    await conn.commit()


async def _load_cobol_file_rows(conn, run_id: str):
    cur = await conn.execute(
        "SELECT file_id, path, program_id, loc, sha256, file_kind "
        "FROM cobol_files WHERE run_id = ? AND file_kind = 'cobol_source' ORDER BY path",
        (run_id,),
    )
    return await cur.fetchall()


async def execute_exploration(run_id: str, conn, events: list) -> None:
    source_dir = RUNS_DIR / run_id / "source"
    if not source_dir.is_dir():
        events.append(PhaseEvent(
            phase="Exploration · Discovery", skill="cobol-discovery", status="BLOCKED",
            detail="source directory missing — run intake first",
        ))
        await _set_session(conn, run_id, "FAILED", finished_at=_now())
        return

    await _set_session(conn, run_id, "RUNNING", started_at=_now(), finished_at="")
    await conn.execute("DELETE FROM cobol_analyses WHERE run_id = ?", (run_id,))
    await conn.execute("DELETE FROM dependency_edges WHERE run_id = ?", (run_id,))
    await conn.commit()

    events.append(PhaseEvent(
        phase="Exploration · Discovery", skill="cobol-discovery", status="OK",
        detail="intake inventory already on disk — using cobol_files rows",
    ))

    rows = await _load_cobol_file_rows(conn, run_id)
    total = len(rows)
    events.append(PhaseEvent(
        phase="Exploration · Structural", skill="cobol-structural-analysis", status="RUNNING",
        detail=f"0/{total} programs parsed",
    ))

    sem = asyncio.Semaphore(MAX_STRUCTURAL_PARALLEL)
    done_count = 0
    lock = asyncio.Lock()

    async def one_file(row: tuple) -> None:
        nonlocal done_count
        file_id, path, program_id, loc, sha256, _kind = row
        events.append(FileEvent(
            run_id=run_id, phase="Exploration · Structural", file_path=path,
            status="RUNNING", detail="parsing divisions, PIC, paragraphs",
        ))
        text = (source_dir / path).read_text(errors="replace")
        struct = core.parse_structural(text)
        async with sem:
            await conn.execute(
                "INSERT INTO cobol_analyses "
                "(analysis_id, run_id, file_id, divisions_json, variables_json, "
                "paragraphs_json, complexity_tier, created_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(ULID()), run_id, file_id,
                    json.dumps(struct["divisions"]),
                    json.dumps(struct["variables_json"]),
                    json.dumps(struct["paragraphs_json"]),
                    struct["complexity_tier"],
                    _now(),
                ),
            )
            await conn.commit()
        events.append(FileEvent(
            run_id=run_id, phase="Exploration · Structural", file_path=path,
            status="OK",
            detail=f"{struct['complexity_tier']} · {len(struct['paragraphs_json'])} paragraphs · "
                   f"{len(struct['calls'])} CALL sites",
        ))
        async with lock:
            done_count += 1
            events.append(PhaseEvent(
                phase="Exploration · Structural", skill="cobol-structural-analysis", status="RUNNING",
                detail=f"{done_count}/{total} programs parsed",
            ))

    if rows:
        await asyncio.gather(*(one_file(r) for r in rows))
    events.append(PhaseEvent(
        phase="Exploration · Structural", skill="cobol-structural-analysis", status="OK",
        detail=f"{total}/{total} programs parsed",
    ))

    events.append(PhaseEvent(
        phase="Exploration · Dependency", skill="cobol-dependency-mapping", status="RUNNING",
        detail="resolving CALL edges",
    ))
    files = inventory_source(source_dir)
    cobol = [f for f in files if f.kind == "cobol_source"]
    path_to_id = {r[1]: r[0] for r in rows}
    edges, open_items = core.build_graph_edges(cobol)
    for e in edges:
        fid = path_to_id.get(e["from_path"])
        tid = path_to_id.get(e["to_path"])
        if fid and tid:
            await conn.execute(
                "INSERT INTO dependency_edges (edge_id, run_id, from_file_id, to_file_id, edge_type) "
                "VALUES (?,?,?,?,?)",
                (str(ULID()), run_id, fid, tid, e["edge_type"]),
            )
    await conn.commit()
    detail = f"{len(edges)} CALL edges"
    if open_items:
        detail += f" · {len(open_items)} unresolved"
    events.append(PhaseEvent(
        phase="Exploration · Dependency", skill="cobol-dependency-mapping",
        status="OK" if not open_items else "BLOCKED",
        detail=detail,
    ))

    events.append(PhaseEvent(
        phase="Exploration · Modules", skill="migration-module-synthesis", status="RUNNING",
        detail="clustering programs by CALL connectivity",
    ))
    pack = core.build_exploration_pack(run_id, source_dir, locked=False)
    await conn.execute(
        "UPDATE exploration_sessions SET draft_pack_json = ?, status = ?, finished_at = ? WHERE run_id = ?",
        (json.dumps(pack), "REVIEW", _now(), run_id),
    )
    await conn.commit()
    mod_count = len(pack.get("modules", []))
    events.append(PhaseEvent(
        phase="Exploration · Modules", skill="migration-module-synthesis", status="OK",
        detail=f"{mod_count} migration module(s) · pack draft ready",
    ))

    events.append(PhaseEvent(
        phase="Exploration · Business logic", skill="cobol-business-logic-extraction",
        status="SKIPPED",
        detail="draft rules embedded in pack — agentic extract (future) replaces stubs",
    ))
