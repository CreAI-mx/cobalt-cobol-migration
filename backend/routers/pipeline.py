"""Work-item pipeline: one planner manifesto, isolated Claude workers, hash
integrator, dotnet build/test gates. Legacy 9-phase crawl is no longer started.
"""
import asyncio
import io
import json
import os
import traceback
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse, Response
import aiosqlite

from db import get_db, open_db
from models import AgentStackConfig, ArchitectureDecision, BusinessLogicExtract, FileEvent, PhaseEvent, RunStatusResponse
from routers.intake import classify_file_kind
import llm
import orchestrator
import parity_demo
import agent_stack
from ulid import ULID

router = APIRouter(prefix="/migration", tags=["pipeline"])

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RUNS_DIR = REPO_ROOT / "migration-state" / "runs"

# Union event stream per run: PhaseEvents are start/end markers, FileEvents are
# granular per-file progress. Both carry a `type` discriminator for SSE consumers.
_run_state: dict[str, list[PhaseEvent | FileEvent]] = {}
_run_tasks: dict[str, asyncio.Task] = {}

# Sentinel phase name marking end-of-stream for the SSE endpoint (replaces the
# old hardcoded `last_count >= 9` magic-number break — audit round-1 finding #5).
_DONE_PHASE = "__done__"

async def _run_phases(run_id: str, conn: aiosqlite.Connection):
    """Work-item orchestrator: one planner manifesto, isolated workers, hash
    integrator, build/test gates. Replaces the 9-phase 1-COBOL-1-file crawl."""
    events = _run_state[run_id]
    await orchestrator.execute_migration(run_id, conn, events)


async def _latest_architecture(conn: aiosqlite.Connection, run_id: str) -> dict:
    row = await _latest_architecture_row(conn, run_id)
    if not row:
        return {"revision": 0, "shape": "clean", "directive": "", "action": "none"}
    return {
        "revision": int(row[0]),
        "shape": row[1],
        "directive": row[2] or "",
        "action": row[3],
    }


async def _poll_architecture_decision(run_id: str) -> dict:
    """Fresh connection so HTTP-committed accepts are visible.

    The pipeline's long-lived conn starts a deferred read snapshot on the first
    SELECT and would otherwise never see architecture_decisions inserts from
    POST /architecture (separate get_db() connection).
    """
    conn = await open_db()
    try:
        return await _latest_architecture(conn, run_id)
    finally:
        await conn.close()


async def _refresh_architecture(
    conn: aiosqlite.Connection, run_id: str, events: list, current: dict,
) -> dict:
    """HITL can Recreate after conversion started. Pause remaining waves until
    Accept; do not silently keep the first accepted shape for the rest of the run."""
    latest = await _poll_architecture_decision(run_id)
    if latest["action"] == "accepted":
        if int(latest["revision"]) != int(current.get("revision") or 0):
            events.append(PhaseEvent(
                phase="Phase 4", skill="cobol-to-csharp-conversion", status="RUNNING",
                detail=f"HITL re-accepted rev {latest['revision']} shape={latest['shape']} — "
                       f"remaining files use this estate",
            ))
        return latest
    events.append(PhaseEvent(
        phase="Phase 4", skill="cobol-to-csharp-conversion", status="RUNNING",
        detail="WAITING — Recreate paused conversion. Accept architecture to continue remaining files with the new estate.",
    ))
    while True:
        latest = await _poll_architecture_decision(run_id)
        if latest["action"] == "accepted":
            events.append(PhaseEvent(
                phase="Phase 4", skill="cobol-to-csharp-conversion", status="RUNNING",
                detail=f"HITL accepted rev {latest['revision']} shape={latest['shape']} — resuming conversion",
            ))
            return latest
        await asyncio.sleep(1.5)


async def _latest_architecture_row(conn: aiosqlite.Connection, run_id: str):
    cursor = await conn.execute(
        "SELECT revision, shape, directive, action, created_at "
        "FROM architecture_decisions WHERE run_id = ? ORDER BY revision DESC LIMIT 1",
        (run_id,),
    )
    return await cursor.fetchone()


async def _wait_for_architecture_accept(conn: aiosqlite.Connection, run_id: str, events: list) -> dict:
    """Block Phase 4 until Step 3 POSTs action=accepted. Phases 0–3 already ran.
    Skip the WAITING chip when Accept is already stored (HITL during 0–3)."""
    latest = await _poll_architecture_decision(run_id)
    if latest["action"] != "accepted":
        events.append(PhaseEvent(
            phase="Phase 4", skill="cobol-to-csharp-conversion", status="RUNNING",
            detail="WAITING — HITL must accept architecture on Step 3 (POST /architecture action=accepted). Phases 0–3 already ran.",
        ))
        while True:
            latest = await _poll_architecture_decision(run_id)
            if latest["action"] == "accepted":
                break
            await asyncio.sleep(1.5)
    events.append(PhaseEvent(
        phase="Phase 4", skill="cobol-to-csharp-conversion", status="RUNNING",
        detail=f"HITL accepted rev {latest['revision']} shape={latest['shape']} — starting conversion",
    ))
    return latest


async def _architecture_response(conn: aiosqlite.Connection, run_id: str) -> ArchitectureDecision:
    row = await _latest_architecture_row(conn, run_id)
    if not row:
        return ArchitectureDecision(run_id=run_id)
    return ArchitectureDecision(
        run_id=run_id,
        revision=int(row[0]),
        shape=row[1],
        directive=row[2] or "",
        action=row[3],
        created_at=row[4],
    )


def _phase_summary(run_id: str) -> list[PhaseEvent]:
    """Collapse the union event stream into one PhaseEvent per phase (latest wins;
    dict preserves first-insertion order), excluding the sentinel and FileEvents."""
    by_phase: dict[str, PhaseEvent] = {}
    for e in _run_state.get(run_id, []):
        if isinstance(e, PhaseEvent) and e.phase != _DONE_PHASE:
            by_phase[e.phase] = e
    return list(by_phase.values())


def _run_is_live(run_id: str) -> bool:
    task = _run_tasks.get(run_id)
    return task is not None and not task.done()


async def _snapshot_events(conn: aiosqlite.Connection, run_id: str) -> None:
    """Overwrite run_events with the current in-memory log. Called periodically
    while live and once more on exit — good enough resolution to answer 'which
    phase is this run stuck at' for a run nobody is watching live."""
    events = _run_state.get(run_id, [])
    rows = []
    for i, e in enumerate(events):
        if isinstance(e, FileEvent):
            rows.append((str(ULID()), run_id, i, "file", e.phase, e.file_path, e.status, e.detail, None))
        else:
            rows.append((str(ULID()), run_id, i, "phase", e.phase, None, e.status, e.detail, e.skill))
    await conn.execute("DELETE FROM run_events WHERE run_id = ?", (run_id,))
    if rows:
        await conn.executemany(
            "INSERT INTO run_events (event_id, run_id, seq, type, phase, file_path, status, detail, skill) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            rows,
        )
    await conn.commit()


async def _snapshot_events_loop(run_id: str, conn: aiosqlite.Connection) -> None:
    """Background heartbeat — persists progress every 3s while the pipeline
    runs, and once more on cancel/exit so the final state is never stale."""
    try:
        while True:
            await asyncio.sleep(3)
            await _snapshot_events(conn, run_id)
    except asyncio.CancelledError:
        await _snapshot_events(conn, run_id)
        raise


async def _execute_run(run_id: str) -> None:
    """Own the SQLite connection for the whole pipeline — the /start request
    returns immediately so the wizard stays interactive."""
    conn = await open_db()
    snapshot_conn = await open_db()
    snapshot_task = asyncio.create_task(_snapshot_events_loop(run_id, snapshot_conn))
    try:
        await _run_phases(run_id, conn)
        phases = _phase_summary(run_id)
        final_status = "FAILED" if any(p.status == "BLOCKED" for p in phases) else "PASSED"
        await conn.execute(
            "UPDATE migration_runs SET status = ?, finished_at = ? WHERE run_id = ?",
            (final_status, datetime.now(timezone.utc).isoformat(), run_id),
        )
        await conn.commit()
    except Exception:
        # str(exc) alone can be empty (e.g. some asyncio/subprocess errors) —
        # that produced an undiagnosable "pipeline crashed: " with nothing
        # after it. Print the real traceback to the server log so a crash is
        # never silent, and surface a non-empty summary in the event detail.
        tb = traceback.format_exc()
        print(f"[_execute_run] run_id={run_id} crashed:\n{tb}", flush=True)
        last_line = tb.strip().splitlines()[-1] if tb.strip() else "unknown error"
        events = _run_state.setdefault(run_id, [])
        events.append(PhaseEvent(
            phase="Phase 4", skill="pipeline", status="BLOCKED",
            detail=f"pipeline crashed: {last_line}"[:400],
        ))
        if not any(isinstance(e, PhaseEvent) and e.phase == _DONE_PHASE for e in events):
            events.append(PhaseEvent(phase=_DONE_PHASE, skill="pipeline", status="OK",
                                     detail="stream complete"))
        try:
            await conn.execute(
                "UPDATE migration_runs SET status = ?, finished_at = ? WHERE run_id = ?",
                ("FAILED", datetime.now(timezone.utc).isoformat(), run_id),
            )
            await conn.commit()
        except Exception:
            pass
    finally:
        snapshot_task.cancel()
        try:
            await snapshot_task
        except asyncio.CancelledError:
            pass
        await snapshot_conn.close()
        await conn.close()


@router.post("/{run_id}/start", response_model=RunStatusResponse)
async def start_pipeline(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    source_dir = RUNS_DIR / run_id / "source"
    if not source_dir.exists():
        raise HTTPException(404, f"No intake found for run_id={run_id} — call POST /migration/intake first")
    if _run_is_live(run_id):
        gate_status = await _latest_gate_status(conn, run_id)
        return RunStatusResponse(
            run_id=run_id, status="RUNNING", phases=_phase_summary(run_id), gate_status=gate_status
        )
    _run_state[run_id] = []
    _run_tasks[run_id] = asyncio.create_task(_execute_run(run_id))
    # migration_runs.status only got written at completion (_execute_run's
    # PASSED/FAILED) — a retry of a FAILED run stayed 'FAILED' in the DB (and
    # therefore in run history) for the whole duration of the retry. Flip it
    # here so history reflects the retry immediately, not just its outcome.
    await conn.execute(
        "UPDATE migration_runs SET status = 'RUNNING', finished_at = NULL WHERE run_id = ?",
        (run_id,),
    )
    await conn.commit()
    gate_status = await _latest_gate_status(conn, run_id)
    return RunStatusResponse(run_id=run_id, status="RUNNING", phases=[], gate_status=gate_status)


@router.get("/{run_id}/status", response_model=RunStatusResponse)
async def get_status(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    if run_id not in _run_state:
        raise HTTPException(404, f"No run in progress or completed for run_id={run_id}")
    phases = _phase_summary(run_id)
    gate_status = await _latest_gate_status(conn, run_id)
    if _run_is_live(run_id):
        status = "RUNNING"
    elif any(p.status == "BLOCKED" for p in phases):
        status = "FAILED"
    else:
        status = "PASSED"
    return RunStatusResponse(
        run_id=run_id, status=status, phases=phases, gate_status=gate_status
    )


@router.get("/{run_id}/detail")
async def get_run_detail(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    """Full picture of ANY run — live or long-dead — sourced entirely from
    persisted tables (migration_runs + run_events), never _run_state. This is
    what makes 'click a past run in history' work after a process restart,
    when the in-memory event log for that run no longer exists."""
    cursor = await conn.execute(
        "SELECT status, source_repo, started_at, finished_at FROM migration_runs WHERE run_id = ?",
        (run_id,),
    )
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(404, f"No run_id={run_id}")
    status, source_repo, started_at, finished_at = row
    cursor = await conn.execute(
        "SELECT type, phase, file_path, status, detail, skill FROM run_events "
        "WHERE run_id = ? ORDER BY seq",
        (run_id,),
    )
    events = []
    for ev_type, phase, file_path, ev_status, detail, skill in await cursor.fetchall():
        if ev_type == "file":
            events.append({
                "type": "file", "run_id": run_id, "phase": phase,
                "file_path": file_path, "status": ev_status, "detail": detail or "",
            })
        else:
            events.append({
                "type": "phase", "phase": phase, "skill": skill or "",
                "status": ev_status, "detail": detail or "",
            })
    plan = await orchestrator.load_plan(conn, run_id)
    return {
        "run_id": run_id, "status": status, "source_repo": source_repo,
        "started_at": started_at, "finished_at": finished_at,
        "live": _run_is_live(run_id), "events": events,
        "plan": plan.to_dict() if plan else None,
    }


async def _latest_gate_status(conn: aiosqlite.Connection, run_id: str) -> str:
    cursor = await conn.execute(
        "SELECT decision FROM gate_decisions WHERE run_id = ? ORDER BY created_at DESC LIMIT 1",
        (run_id,),
    )
    row = await cursor.fetchone()
    return row[0] if row else "none"


@router.get("/{run_id}/gate/history")
async def get_gate_history(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    """Real, persisted decision history — append-only, never overwritten. User
    feedback: a rejection comment must stay visible and traceable as a real
    request, not vanish into ephemeral client state when the reviewer revisits."""
    cursor = await conn.execute(
        "SELECT decision, comment, created_at FROM gate_decisions "
        "WHERE run_id = ? ORDER BY created_at ASC",
        (run_id,),
    )
    rows = await cursor.fetchall()
    return [{"decision": r[0], "comment": r[1], "created_at": r[2]} for r in rows]


@router.post("/{run_id}/gate", response_model=RunStatusResponse)
async def set_gate_decision(run_id: str, body: dict, conn: aiosqlite.Connection = Depends(get_db)):
    """Human Approval Gate (Phase 7): persist the reviewer's decision + comment —
    a rejection with no stored comment is invisible to whoever owns the fix."""
    decision = body.get("decision")
    # "pending" is accepted so "Revisit decision" can persist a reset — otherwise
    # the frontend's local reset to 'none' gets clobbered back to the DB's last
    # 'rejected'/'approved' row on the next status poll (real bug found live).
    if decision not in ("approved", "rejected", "pending"):
        raise HTTPException(422, "decision must be 'approved', 'rejected', or 'pending'")
    comment = body.get("comment", "")

    cursor = await conn.execute("SELECT 1 FROM migration_runs WHERE run_id = ?", (run_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(404, f"No run found for run_id={run_id}")

    await conn.execute(
        "INSERT INTO gate_decisions (decision_id, run_id, decision, comment, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (str(ULID()), run_id, decision, comment, datetime.now(timezone.utc).isoformat()),
    )
    await conn.commit()

    phases = _phase_summary(run_id) if run_id in _run_state else []
    blocked = any(p.status == "BLOCKED" for p in phases)
    status = "FAILED" if blocked else ("PASSED" if phases else "RUNNING")
    return RunStatusResponse(run_id=run_id, status=status, phases=phases, gate_status=decision)


@router.get("/{run_id}/architecture", response_model=ArchitectureDecision)
async def get_architecture(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    cursor = await conn.execute("SELECT 1 FROM migration_runs WHERE run_id = ?", (run_id,))
    if not await cursor.fetchone():
        raise HTTPException(404, f"No run found for run_id={run_id}")
    return await _architecture_response(conn, run_id)


@router.post("/{run_id}/architecture", response_model=ArchitectureDecision)
async def set_architecture(run_id: str, body: dict, conn: aiosqlite.Connection = Depends(get_db)):
    """HITL Step 3: persist a shape + directive. action=recreated redraws the
    estate; action=accepted unblocks Phase 4. Append-only revisions."""
    shape = body.get("shape", "clean")
    if shape not in ("clean", "per-program", "one-to-one"):
        raise HTTPException(422, "shape must be 'clean', 'per-program', or 'one-to-one'")
    action = body.get("action")
    if action not in ("recreated", "accepted"):
        raise HTTPException(422, "action must be 'recreated' or 'accepted'")
    directive = body.get("directive") or ""

    cursor = await conn.execute("SELECT 1 FROM migration_runs WHERE run_id = ?", (run_id,))
    if not await cursor.fetchone():
        raise HTTPException(404, f"No run found for run_id={run_id}")

    cursor = await conn.execute(
        "SELECT COALESCE(MAX(revision), 0) FROM architecture_decisions WHERE run_id = ?",
        (run_id,),
    )
    rev_row = await cursor.fetchone()
    revision = int(rev_row[0] if rev_row else 0) + 1
    now = datetime.now(timezone.utc).isoformat()
    await conn.execute(
        "INSERT INTO architecture_decisions "
        "(decision_id, run_id, revision, shape, directive, action, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(ULID()), run_id, revision, shape, directive, action, now),
    )
    await conn.commit()
    if action == "accepted" and run_id in _run_state:
        _run_state[run_id].append(PhaseEvent(
            phase="Phase 4", skill="cobol-to-csharp-conversion", status="RUNNING",
            detail=f"HITL accepted rev {revision} shape={shape} — starting conversion",
        ))
    elif action == "recreated" and run_id in _run_state:
        _run_state[run_id].append(PhaseEvent(
            phase="Phase 4", skill="cobol-to-csharp-conversion", status="RUNNING",
            detail="WAITING — Recreate stored. Accept architecture to continue remaining files with the new estate.",
        ))
    return ArchitectureDecision(
        run_id=run_id, revision=revision, shape=shape, directive=directive,
        action=action, created_at=now,
    )


@router.get("/{run_id}/events")
async def stream_events(run_id: str):
    """Stream the union event list (PhaseEvent | FileEvent) as SSE, each JSON
    line carrying its `type` discriminator. Terminates on the __done__ sentinel
    PhaseEvent instead of a hardcoded event count."""
    async def gen():
        # Deadline must outlive agentic phases: N headless LLM calls can take
        # minutes, unlike the old parse-only pipeline. 30 min hard wall.
        deadline = asyncio.get_event_loop().time() + 30 * 60
        last_count = 0
        done = False
        while asyncio.get_event_loop().time() < deadline:
            events = _run_state.get(run_id, [])
            if len(events) > last_count:
                for e in events[last_count:]:
                    yield f"data: {json.dumps(e.model_dump())}\n\n"
                    if isinstance(e, PhaseEvent) and e.phase == _DONE_PHASE:
                        done = True
                last_count = len(events)
            if done:
                break
            await asyncio.sleep(0.1)
    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/{run_id}/extracts", response_model=list[BusinessLogicExtract])
async def get_extracts(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    """Phase 2 output: business logic extracts per COBOL source file. The frontend
    consumes suggested_component_name for the Step 3 component proposal."""
    cursor = await conn.execute(
        "SELECT e.extract_id, e.file_id, f.path, e.user_stories_json, "
        "e.business_rules_json, e.suggested_component_name, e.created_at "
        "FROM business_logic_extracts e JOIN cobol_files f ON f.file_id = e.file_id "
        "WHERE e.run_id = ? ORDER BY f.path",
        (run_id,),
    )
    rows = await cursor.fetchall()
    return [
        BusinessLogicExtract(
            extract_id=r[0], file_id=r[1], path=r[2],
            user_stories=json.loads(r[3]), business_rules=json.loads(r[4]),
            suggested_component_name=r[5], created_at=r[6],
        )
        for r in rows
    ]


@router.get("/{run_id}/cost")
async def get_cost(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    """Real cost_logs rows (Phase 2 headless calls write them). Empty list until
    an agentic phase has actually spent tokens — never fabricated numbers."""
    cursor = await conn.execute(
        "SELECT phase, agent_id, input_tokens, output_tokens, cost_usd, latency_ms, created_at "
        "FROM cost_logs WHERE run_id = ? ORDER BY created_at",
        (run_id,),
    )
    rows = await cursor.fetchall()
    return [
        {"phase": r[0], "agent_id": r[1], "input_tokens": r[2], "output_tokens": r[3],
         "cost_usd": r[4], "latency_ms": r[5], "created_at": r[6]}
        for r in rows
    ]


@router.get("/{run_id}/plan")
async def get_plan(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    """The manifesto the UI renders — N work items, never a fictitious 46-file tree."""
    plan = await orchestrator.load_plan(conn, run_id)
    if not plan:
        raise HTTPException(404, f"No migration plan for run_id={run_id}")
    payload = plan.to_dict()
    payload["live"] = _run_is_live(run_id)
    return payload


@router.post("/{run_id}/plan")
async def create_plan(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    """Idempotent planner. Does not start conversion."""
    source_dir = RUNS_DIR / run_id / "source"
    if not source_dir.exists():
        raise HTTPException(404, f"No intake found for run_id={run_id}")
    existing = await orchestrator.load_plan(conn, run_id)
    if existing and existing.work_items:
        return existing.to_dict()
    events: list = []
    plan = await orchestrator.ensure_plan(conn, run_id, events)
    return plan.to_dict()


# The machine already has a real GitHub credential stored at ~/.git-credentials
# under the OS user's real HOME (not this backend's own HOME) — user 2026-09-15:
# "ya aqui local esta el github registrado". Reuse it via git's own credential
# helper instead of asking for a token in the UI.
_REAL_HOME = "/home/frg"


async def _github_credential() -> tuple[str, str]:
    """Ask git's stored credential helper for github.com creds — never read
    ~/.git-credentials directly, never log the result."""
    proc = await asyncio.create_subprocess_exec(
        "git", "credential", "fill",
        env={**os.environ, "HOME": _REAL_HOME},
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(b"protocol=https\nhost=github.com\n\n")
    if proc.returncode != 0:
        raise HTTPException(502, f"No stored GitHub credential found: {err.decode(errors='replace')[:300]}")
    fields = dict(
        line.split("=", 1) for line in out.decode(errors="replace").splitlines() if "=" in line
    )
    username, password = fields.get("username"), fields.get("password")
    if not username or not password:
        raise HTTPException(502, "Stored GitHub credential is missing username/password.")
    return username, password


async def _github_create_repo(username: str, password: str, name: str) -> str:
    """Create a new PUBLIC repo under the credential's owner. Returns its
    https clone URL (no credentials embedded). Shells out to curl — no HTTP
    client library is installed in this venv, and this is a single call."""
    proc = await asyncio.create_subprocess_exec(
        "curl", "-s", "-u", f"{username}:{password}",
        "-H", "Accept: application/vnd.github+json",
        "-X", "POST", "https://api.github.com/user/repos",
        "-d", json.dumps({"name": name, "private": False, "auto_init": False}),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise HTTPException(502, f"curl failed calling GitHub API: {err.decode(errors='replace')[:300]}")
    payload = json.loads(out.decode(errors="replace"))
    if "clone_url" not in payload:
        raise HTTPException(502, f"GitHub repo creation failed: {payload.get('message', payload)}")
    return payload["clone_url"]


async def _git_push_with_stored_credential(csharp: Path, clone_url: str) -> str:
    """git init/commit/push using the machine's real HOME so git's own stored
    credential helper supplies auth — no token ever touches this project's
    .git/config, argv, or logs."""
    env = {**os.environ, "HOME": _REAL_HOME, "GIT_TERMINAL_PROMPT": "0"}

    async def run(*args: str) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            "git", *args, cwd=str(csharp), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        return proc.returncode, out.decode(errors="replace")

    if not (csharp / ".git").is_dir():
        code, out = await run("init", "-b", "main")
        if code != 0:
            raise HTTPException(502, f"git init failed: {out[:400]}")
    await run("config", "user.email", "cobalt@localhost")
    await run("config", "user.name", "Cobalt Migration")
    await run("add", "-A")
    code, out = await run("commit", "-m", "Migrated by Cobalt")
    if code != 0 and "nothing to commit" not in out:
        raise HTTPException(502, f"git commit failed: {out[:400]}")
    code, out = await run("push", "-f", clone_url, "HEAD:main")
    if code != 0:
        raise HTTPException(502, f"git push failed: {out[:400]}")
    return clone_url


@router.post("/{run_id}/github-push")
async def github_push(run_id: str, body: dict):
    """Uses the machine's already-registered GitHub credential — no token
    input required from the user."""
    repo_url = (body.get("repo_url") or "").strip()
    repo_name = (body.get("repo_name") or f"cobalt-{run_id.lower()}").strip()

    csharp = RUNS_DIR / run_id / "csharp"
    if not csharp.is_dir():
        raise HTTPException(404, "No generated C# yet")

    # User 2026-09-15: "el github destino sin nada" — push the generated
    # C# exactly as-is, no extra files (no CI workflow, nothing added).
    username, password = await _github_credential()
    if not repo_url:
        repo_url = await _github_create_repo(username, password, repo_name)

    pushed_url = await _git_push_with_stored_credential(csharp, repo_url)
    return {"repo_url": pushed_url}


@router.post("/{run_id}/parity-demo")
async def parity_demo_run(run_id: str, body: dict | None = None):
    """Run COBOL oracle and/or dotnet test for the Step 5 parity sandbox."""
    root = RUNS_DIR / run_id
    if not root.is_dir():
        raise HTTPException(404, f"No run_id={run_id}")
    side = (body or {}).get("side", "both")
    return await asyncio.to_thread(parity_demo.run_parity_demo, run_id, side)



@router.post("/{run_id}/agent-rerun", response_model=RunStatusResponse)
async def agent_rerun_pipeline(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    """Re-run foreman with agent-stack circumstance injected into conversion prompts."""
    source_dir = RUNS_DIR / run_id / "source"
    if not source_dir.exists():
        raise HTTPException(404, f"No intake found for run_id={run_id}")
    if _run_is_live(run_id):
        gate_status = await _latest_gate_status(conn, run_id)
        return RunStatusResponse(
            run_id=run_id, status="RUNNING", phases=_phase_summary(run_id), gate_status=gate_status,
        )
    brief = agent_stack.circumstance_for_run(run_id)
    _run_state[run_id] = []
    if brief.strip():
        detail = f"Agent rerun — circumstance ({len(brief.strip())} chars): {brief.strip()[:280]}"
        marker_status = "RUNNING"
    else:
        detail = "Agent rerun — no circumstance brief; set one in Agent stack for prompt injection."
        marker_status = "OK"
    _run_state[run_id].append(
        PhaseEvent(phase="AgentSession", skill="agent-stack", status=marker_status, detail=detail),
    )
    _run_tasks[run_id] = asyncio.create_task(_execute_run(run_id))
    await conn.execute(
        "UPDATE migration_runs SET status = 'RUNNING', finished_at = NULL WHERE run_id = ?",
        (run_id,),
    )
    await conn.commit()
    gate_status = await _latest_gate_status(conn, run_id)
    return RunStatusResponse(run_id=run_id, status="RUNNING", phases=[], gate_status=gate_status)


@router.get("/{run_id}/agent-stack", response_model=AgentStackConfig)
async def get_agent_stack(run_id: str, conn: aiosqlite.Connection = Depends(get_db)):
    cursor = await conn.execute("SELECT 1 FROM migration_runs WHERE run_id = ?", (run_id,))
    if not await cursor.fetchone():
        raise HTTPException(404, f"No run_id={run_id}")
    cfg = agent_stack.load_config(run_id)
    return AgentStackConfig(**cfg)


@router.put("/{run_id}/agent-stack", response_model=AgentStackConfig)
async def put_agent_stack(run_id: str, body: AgentStackConfig, conn: aiosqlite.Connection = Depends(get_db)):
    cursor = await conn.execute("SELECT 1 FROM migration_runs WHERE run_id = ?", (run_id,))
    if not await cursor.fetchone():
        raise HTTPException(404, f"No run_id={run_id}")
    tools = body.tools or {}
    cfg = agent_stack.save_config(run_id, circumstance=body.circumstance, tools=tools)
    await conn.execute(
        "UPDATE migration_runs SET notes = ? WHERE run_id = ?",
        (body.circumstance or None, run_id),
    )
    await conn.commit()
    return AgentStackConfig(**cfg)


@router.get("/{run_id}/artifact.zip")
async def download_artifact(run_id: str):
    csharp = RUNS_DIR / run_id / "csharp"
    if not csharp.is_dir():
        raise HTTPException(404, "No generated C# yet")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in csharp.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(csharp)
            if any(part in {"bin", "obj"} for part in rel.parts):
                continue
            zf.write(path, str(rel))
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.zip"'},
    )
